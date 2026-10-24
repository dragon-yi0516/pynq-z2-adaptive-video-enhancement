# =============================================================================
# 一条命令跑完一个硬件阶段：建基础 BD -> 打包 IP -> 插进 BD -> 出 bitstream
#
# 用法（在 Ubuntu 任意目录下都能跑）：
#   vivado -mode batch -nojournal -notrace \
#          -source /home/xu/OV5640_capture_only/ai_video/tools/stage_flow.tcl \
#          -tclargs 1
#
#   -tclargs 1        阶段 1（纯直通 IP）
#   -tclargs 2        阶段 2（AXI-Lite 寄存器）
#   -tclargs 3        阶段 3（特征提取）
#   -tclargs 6        阶段 6（MLP 集成，需先跑完 HLS 导出 IP）
#   -tclargs 7        阶段 7（可重构阵列，需先跑完 HLS 导出 IP）
#   -tclargs 12       阶段 12（连续参数 + 四象限统计，需先跑完 HLS 导出 IP）
#   -tclargs 13       阶段 13（连续参数 + 四象限 + 分屏输出，需先跑完 HLS 导出 IP）
#
#   末尾再加一个 clean 会先重建基础 BD：  -tclargs 1 clean
# =============================================================================

set _here    [file normalize [file dirname [info script]]]
set _ai_root [file normalize [file join $_here ..]]
source [file join $_here insert_axis_video_proc_common.tcl]

# 把一段脚本包起来跑：失败就打印清楚的原因并以非 0 退出。
# 这样 build_overlay.sh 里的 set -e 能立刻停下，日志末尾也能直接看到原因，
# 不用在一大堆 INFO 里翻找。
proc run_or_die {desc body} {
    if {[catch { uplevel 1 $body } err]} {
        puts ""
        puts "############################################################"
        puts "# 失败于：$desc"
        puts "# 错误  ：$err"
        puts "# 调用栈：$::errorInfo"
        puts "############################################################"
        exit 1
    }
}

set stage [lindex $argv 0]
if {$stage eq ""} {
    error "用法：-tclargs <1|2|3|6|7|12|13> \[clean\]"
}
set do_clean 0
if {[lsearch -exact $argv clean] >= 0} { set do_clean 1 }

set bs_dir       [ai_video::bitstream_dir]
set overlay_name "cv_ov5640"
set proj_dir     [file join $bs_dir $overlay_name]
set xpr          [file join $proj_dir "${overlay_name}.xpr"]

puts "============================================================"
puts "ai_video 阶段 $stage"
puts "  ai_video 根 : $_ai_root"
puts "  bitstream   : $bs_dir"
puts "  工程        : $xpr"
puts "  clean       : $do_clean"
puts "============================================================"

# ---- 0. 需要时生成基础 BD ---------------------------------------------------
if {$do_clean && [file exists $proj_dir]} {
    # clean 的语义就是“从这个阶段从头再来”。只跑 create_project -force 不清目录的话，
    # 旧的 runs/ 和 .gen/ 会留下来，容易出“改了脚本但结果没变”的怪事。
    set _a [file normalize $bs_dir]
    set _b [file normalize $proj_dir]
    if {[string first $_a $_b] == 0} {
        puts "== clean：删除旧工程目录 $proj_dir =="
        file delete -force $proj_dir
    }
}

if {$do_clean || ![file exists $xpr]} {
    set base_tcl [file join $bs_dir "${overlay_name}.tcl"]
    if {![file exists $base_tcl]} {
        error "在 $bs_dir 里找不到 ${overlay_name}.tcl，无法生成基础 BD"
    }
    puts "== 生成基础 Block Design（${overlay_name}.tcl，需要几分钟）=="
    set _cwd [pwd]
    cd $bs_dir
    run_or_die "生成基础 BD" [list source $base_tcl]
    cd $_cwd
} else {
    # 2024.2 新增：先确认已有工程就是 2024.2 建的。
    # 2018.3 建的 .xpr 在 2024.2 里打开会触发 IP 升级和接口变化，
    # 后面 “插 IP” 那一步经常卡在莫名其妙的报错上。宁可让你重建，也别在这儿耗时间。
    set _fh [open $xpr r]
    set _head [read $_fh 400]
    close $_fh
    set _old_ver ""
    if {[regexp {Product Version:\s*Vivado v([0-9]+\.[0-9]+)} $_head -> _old_ver]} {
        if {$_old_ver ne "2024.2"} {
            puts ""
            puts "############################################################"
            puts "# 现有工程是 Vivado v$_old_ver 建的："
            puts "#   $xpr"
            puts "# 本套脚本针对 Vivado 2024.2，跨版本打开会出各种接口不匹配的问题。"
            puts "# 请先重建基础 BD（会删掉这个旧工程目录）："
            puts "#   bash build_overlay.sh $stage clean"
            puts "############################################################"
            exit 1
        }
    }
    puts "== 已存在 2024.2 工程，直接在它上面改（要重建请加 clean）=="
}

# ---- 1./2. 按阶段选中脚本 ---------------------------------------------------
set pkg_tcl ""
set ins_tcl ""
switch -- $stage {
    1 {
        set pkg_tcl [file join $_ai_root stage01_axis_passthrough tcl package_ip.tcl]
        set ins_tcl [file join $_ai_root stage01_axis_passthrough tcl insert_axis_video_proc.tcl]
    }
    2 {
        set pkg_tcl [file join $_ai_root stage02_axil_regs tcl package_ip.tcl]
        set ins_tcl [file join $_ai_root stage02_axil_regs tcl insert_axil_regs.tcl]
    }
    3 {
        set pkg_tcl [file join $_ai_root stage03_feature_extract tcl package_ip.tcl]
        set ins_tcl [file join $_ai_root stage03_feature_extract tcl insert_feature_extract.tcl]
    }
    6 {
        set pkg_tcl [file join $_ai_root stage06_mlp_integrate tcl package_ip.tcl]
        set ins_tcl [file join $_ai_root stage06_mlp_integrate tcl insert_mlp.tcl]
    }
    7 {
        set pkg_tcl [file join $_ai_root stage07_reconfig_array tcl package_ip.tcl]
        set ins_tcl [file join $_ai_root stage07_reconfig_array tcl insert_reconfig.tcl]
    }
    12 {
        set pkg_tcl [file join $_ai_root stage12_adaptive tcl package_ip.tcl]
        set ins_tcl [file join $_ai_root stage12_adaptive tcl insert_adaptive.tcl]
    }
    13 {
        set pkg_tcl [file join $_ai_root stage13_split tcl package_ip.tcl]
        set ins_tcl [file join $_ai_root stage13_split tcl insert_split.tcl]
    }
    default {
        error "不支持的阶段 $stage（只能是 1/2/3/6/7/12/13）"
    }
}

foreach f [list $pkg_tcl $ins_tcl] {
    if {![file exists $f]} { error "找不到脚本 $f" }
}

puts "== 步骤 1/3：打包自定义 IP =="
run_or_die "打包自定义 IP（阶段 $stage）" [list source $pkg_tcl]

puts "== 步骤 2/3：插入 Block Design =="
run_or_die "插入 Block Design（阶段 $stage）" [list source $ins_tcl]

puts "== 步骤 3/3：综合 + 实现 + 生成 bitstream =="
run_or_die "综合/实现/生成 bitstream" [list source [file join $_here build_and_copy.tcl]]

puts ""
puts "############################################################"
puts "#  阶段 $stage 全部完成"
puts "#  $bs_dir/${overlay_name}.bit  /  .hwh"
puts "#  $_ai_root/overlay/${overlay_name}.bit  /  .hwh"
puts "############################################################"
