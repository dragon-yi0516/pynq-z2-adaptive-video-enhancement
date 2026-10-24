# =============================================================================
# 综合 + 实现 + 生成 bitstream，并把产物拷回两个地方
#
# 为什么不直接用原工程的 build_bitstream.tcl：
#   1. 原脚本用相对路径（./cv_ov5640/...），必须先 cd 到 bitstream 目录；
#      本脚本自定位，在哪个目录执行都行。
#   2. 原脚本每次都调 make_wrapper，工程里已有 wrapper 时会重复添加；
#      本脚本改成“没有才生成”。
#   3. 生成后把 .bit/.hwh 各拷一份到 bitstream/ 和 ai_video/overlay/，
#      上位机不用再手动挪文件。
# =============================================================================

set _here    [file normalize [file dirname [info script]]]
set _ai_root [file normalize [file join $_here ..]]

source [file join $_here insert_axis_video_proc_common.tcl]

set overlay_name "cv_ov5640"
set design_name  "cv_ov5640"
set top_name     "${design_name}_wrapper"

set bs_dir       [ai_video::bitstream_dir]
set proj_dir     [file join $bs_dir $overlay_name]
set xpr          [file join $proj_dir "${overlay_name}.xpr"]
set bd_path      [file join $proj_dir "${overlay_name}.srcs" sources_1 bd $design_name "${design_name}.bd"]
set wrapper_path [file join $proj_dir "${overlay_name}.srcs" sources_1 bd $design_name hdl "${top_name}.v"]
set runs_dir     [file join $proj_dir "${overlay_name}.runs"]

if {![file exists $xpr]} {
    error "找不到工程 $xpr （先跑 cv_ov5640.tcl 生成基础 BD）"
}
if {![file exists $bd_path]} {
    error "找不到 Block Design $bd_path"
}

# 工程可能已经在这个 Vivado 会话里打开了（比如刚跑完 cv_ov5640.tcl），
# 2024.2 不允许对同一个工程再 open_project 一次，所以统一走这个封装。
ai_video::open_project_if_needed $xpr

open_bd_design $bd_path
set bd_files [get_files -quiet $bd_path]
if {[llength $bd_files] == 0} {
    error "工程里没有登记 $bd_path"
}

# ---- wrapper：只在缺失时生成 ------------------------------------------------
if {![file exists $wrapper_path]} {
    puts "== 生成 HDL wrapper =="
    make_wrapper -files $bd_files -top
}
if {[llength [get_files -quiet ${top_name}.v]] == 0} {
    add_files -norecurse $wrapper_path
}
set_property top $top_name [current_fileset]
update_compile_order -fileset sources_1
close_bd_design [current_bd_design]

# ---- 综合 + 实现 ------------------------------------------------------------
puts "== 重新综合（reset_run synth_1）=="
reset_run synth_1

puts "== 跑实现并生成 bitstream（首次约 10~25 分钟，请等）=="
# 并行度：export VIVADO_JOBS=8 可以改大（内存不够就调小）
set jobs 4
if {[info exists ::env(VIVADO_JOBS)]} { set jobs $::env(VIVADO_JOBS) }
launch_runs impl_1 -to_step write_bitstream -jobs $jobs
wait_on_run impl_1

set prog [get_property PROGRESS [get_runs impl_1]]
set stat [get_property STATUS   [get_runs impl_1]]
puts "impl_1: PROGRESS=$prog  STATUS=$stat"
if {$prog ne "100%"} {
    set msg "实现没跑完：PROGRESS=$prog STATUS=$stat，请看日志 $runs_dir/impl_1/runme.log"
    error $msg
}

# ---- 检查产物 --------------------------------------------------------------
set bit_src [file join $runs_dir impl_1 "${top_name}.bit"]

# .hwh 的位置在 Vivado 版本之间变过，2024.2 已经不放 .srcs 了：
#   2018.3 -> <proj>.srcs/sources_1/bd/<bd>/hw_handoff/<bd>.hwh
#   2024.2 -> <proj>.gen /sources_1/bd/<bd>/hw_handoff/<bd>.hwh
# 两个都找，最后再用 find 兜一遍，免得又因为路径变化白跑一次实现。
set hwh_src ""
foreach c [list \
        [file join $proj_dir "${overlay_name}.gen"  sources_1 bd $design_name hw_handoff "${design_name}.hwh"] \
        [file join $proj_dir "${overlay_name}.srcs" sources_1 bd $design_name hw_handoff "${design_name}.hwh"] ] {
    if {[file exists $c]} { set hwh_src $c ; break }
}
if {$hwh_src eq ""} {
    if {![catch { exec find $proj_dir -name "${design_name}.hwh" -type f } hits] && [llength $hits] > 0} {
        set hwh_src [lindex $hits 0]
    }
}
puts "  产物 .bit : $bit_src"
puts "  产物 .hwh : $hwh_src"
foreach f [list $bit_src $hwh_src] {
    if {$f eq "" || ![file exists $f]} { error "没找到产物 $f" }
}

# ---- 时序检查（不收敛就大声报警，并把报告开头打出来）------------------------
# 为什么要把报告前 40 行打到终端：
#   只打印一句“可能未收敛”很容易被当成噪音划过去（阶段 7 就真发生了：
#   日志里其实有 WNS=-5.093，但没人注意，于是上板画面不对又回头查了很久）。
#   把 WNS/TNS 和最差路径的起点终点直接怼到屏幕上，一眼就能看见。
set rpts [glob -nocomplain -directory [file join $runs_dir impl_1] *_timing_summary_routed.rpt]
if {[llength $rpts] > 0} {
    set rpt [lindex $rpts 0]
    set fd [open $rpt r]
    set met 0
    while {[gets $fd line] >= 0} {
        if {[string first "All user specified timing constraints are met" $line] >= 0} {
            set met 1
            break
        }
    }
    close $fd
    if {$met} {
        puts "== 时序收敛：OK =="
    } else {
        puts ""
        puts "############################################################"
        puts "# !! 时序没收敛（timing failed）"
        puts "# !! bitstream 虽然生成了，但上板可能算错，不能算验收通过。"
        puts "# !! 报告：$rpt"
        puts "# 下面是每条违例路径的 Slack / 起点 / 终点（直接看是谁的问题）："
        puts "############################################################"
        set fd [open $rpt r]
        set n 0
        while {[gets $fd line] >= 0 && $n < 60} {
            # 只挑有用的行，别把报告的表头刷一屏
            if {[string first "Slack (" $line] >= 0 ||
                [string first "Source:" $line] >= 0 ||
                [string first "Destination:" $line] >= 0 ||
                [string first "Path Group:" $line] >= 0 ||
                [string first "Clock Summary" $line] >= 0 ||
                [string first "Intra Clock Table" $line] >= 0} {
                puts "  | [string trim $line]"
                incr n
            }
        }
        close $fd
        puts "# 完整报告：$rpt"
        puts "############################################################"
    }
} else {
    puts "（没找到 routed 时序报告，跳过时序检查）"
}

# ---- 拷贝到两个位置 ---------------------------------------------------------
set ov_out [file join $_ai_root overlay]
file mkdir $ov_out

file copy -force $bit_src [file join $bs_dir "${overlay_name}.bit"]
file copy -force $hwh_src [file join $bs_dir "${overlay_name}.hwh"]
file copy -force $bit_src [file join $ov_out "${overlay_name}.bit"]
file copy -force $hwh_src [file join $ov_out "${overlay_name}.hwh"]

puts ""
puts "============================================================"
puts "bitstream 生成完成，已自动拷贝到："
puts "  $bs_dir/${overlay_name}.bit"
puts "  $bs_dir/${overlay_name}.hwh"
puts "  $ov_out/${overlay_name}.bit"
puts "  $ov_out/${overlay_name}.hwh"
puts "============================================================"
