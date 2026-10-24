# =============================================================================
# 阶段 7：把 axis_video_proc(v1.6，含三模式重构阵列 + MLP 握手) 和
#         HLS 的 mlp_engine 一起插进 BD 并连线
#
# 为什么这个脚本不直接用 tools/insert_axis_video_proc_common.tcl：
#   阶段 6/7 除了插自己的 IP，还要额外插一个 HLS IP、加一个反相器（HLS 的
#   ap_rst 是高有效，而 PL 复位是低有效），并连 8 根握手线。
#   这一段“多出来的事”只有本阶段有，单独写反而更清楚。
#
# 前置（按顺序）：
#   1. stage07_reconfig_array/tcl/package_ip.tcl       -> 我们的 IP
#   2. stage05_mlp_hls/hls/script.tcl                  -> HLS 导出 mlp_engine IP
#   3. cv_ov5640.tcl                                   -> 生成基础 BD
#
# 用法：
#   cd <Pynq_CV_OV5640_master>/boards/Pynq-Z2/ov5640/bitstream
#   vivado -mode batch -source cv_ov5640.tcl -notrace
#   vivado -mode batch -source <ai_video>/stage07_reconfig_array/tcl/insert_reconfig.tcl -notrace
#   vivado -mode batch -source build_bitstream.tcl -notrace
# =============================================================================

set here          [file normalize [file dirname [info script]]]
set stage_dir     [file normalize [file join $here ..]]
set ai_video_root [file normalize [file join $here .. ..]]
# 复用公共脚本里的“找 bitstream 目录”逻辑（也支持 AI_VIDEO_BITSTREAM_DIR 覆盖）
source [file join $ai_video_root tools insert_axis_video_proc_common.tcl]
set bs_dir        [ai_video::bitstream_dir]
set proc_ip_repo  [file normalize [file join $stage_dir ip_repo]]
set hls_ip_repo   [file normalize [file join $stage_dir .. stage05_mlp_hls mlp_engine_prj solution1 impl ip]]

set proc_vlnv     "user.org:user:axis_video_proc:1.6"
set mlp_vlnv      "user.org:user:mlp_engine:1.0"

set overlay_name  "cv_ov5640"
set design_name   "cv_ov5640"

if {![file exists $hls_ip_repo]} {
    error "找不到 HLS 导出的 IP: $hls_ip_repo\n请先跑 stage05_mlp_hls/hls/script.tcl 导出 IP。"
}

# 找不到端口时把实际端口列出来，避免只看到一句 “pin not found” 无从下手
proc need_pin {cell name} {
    set p [get_bd_pins -quiet ${cell}/${name}]
    if {[llength $p] == 0} {
        puts "ERROR: 找不到 ${cell}/${name}。该 cell 的实际端口："
        foreach q [get_bd_pins ${cell}/*] { puts "    [get_property NAME $q]" }
        error "缺少端口 ${cell}/${name}"
    }
    return $p
}

# HLS 导出的标量端口会带 _V 后缀（综合日志里是 luma_V / contrast_V / sharpness_V），
# 返回值端口一般是 ap_return。按候选名逐个试 + 大小写模糊匹配，免得因为后缀差异卡住。
proc mlp_pin {cell name} {
    foreach c [list $name "${name}_V" "ap_${name}" "ap_${name}_V"] {
        set p [get_bd_pins -quiet ${cell}/${c}]
        if {[llength $p] > 0} { return [lindex $p 0] }
    }
    set lname [string tolower $name]
    foreach q [get_bd_pins -quiet ${cell}/*] {
        set n [string tolower [get_property NAME $q]]
        if {$n eq $lname || $n eq "${lname}_v"} { return $q }
    }
    if {[string match "*return*" $lname]} {
        foreach q [get_bd_pins -quiet ${cell}/*] {
            if {[string match "*return*" [string tolower [get_property NAME $q]]]} { return $q }
        }
    }
    puts "ERROR: 在 $cell 上找不到端口 $name。该 cell 的实际端口："
    foreach q [get_bd_pins -quiet ${cell}/*] { puts "    [get_property NAME $q]" }
    error "缺少端口 ${cell}/${name}"
}

puts "== 阶段 7：插入 axis_video_proc(含重构阵列) + mlp_engine =="
puts "  BD 目录: $bs_dir"

ai_video::open_project_if_needed [file join $bs_dir ${overlay_name} ${overlay_name}.xpr]

foreach repo [list $proc_ip_repo $hls_ip_repo] {
    set keep {}
    foreach p [get_property ip_repo_paths [current_project]] {
        set pn [file normalize $p]
        if {[file exists $pn]} { lappend keep $pn }
    }
    if {[lsearch -exact $keep $repo] < 0} { lappend keep $repo }
    set_property ip_repo_paths $keep [current_project]
}
update_ip_catalog -rebuild

ai_video::close_open_bd
open_bd_design [file join $bs_dir ${overlay_name} "${overlay_name}.srcs" sources_1 bd ${design_name} "${design_name}.bd"]

foreach cell {axis_video_proc_0 mlp_engine_0 mlp_rst_inv} {
    set old [get_bd_cells -quiet $cell]
    if {[llength $old] > 0} {
        puts "  删除已存在的 $cell"
        delete_bd_objs $old
    }
}

# ---- 1. 视频处理 IP ---------------------------------------------------------
create_bd_cell -type ip -vlnv $proc_vlnv axis_video_proc_0

set old_net [get_bd_intf_nets -quiet v_demosaic_0_m_axis_video]
if {[llength $old_net] > 0} { delete_bd_objs $old_net }
connect_bd_intf_net -intf_net v_demosaic_0_m_axis_video \
    [get_bd_intf_pins v_demosaic_0/m_axis_video] \
    [get_bd_intf_pins axis_video_proc_0/s_axis_video]
connect_bd_intf_net -intf_net axis_video_proc_0_m_axis_video \
    [get_bd_intf_pins axis_video_proc_0/m_axis_video] \
    [get_bd_intf_pins axi_vdma_0/S_AXIS_S2MM]

ai_video::connect_if_open [need_pin axis_video_proc_0 aclk]    [get_bd_pins processing_system7_0/FCLK_CLK0]
ai_video::connect_if_open [need_pin axis_video_proc_0 aresetn] [get_bd_pins rst_ps7_0_100M/peripheral_aresetn]

# ---- 2. 扩一路 AXI-Lite 给 axis_video_proc ---------------------------------
set mi [get_property CONFIG.NUM_MI [get_bd_cells ps7_0_axi_periph]]
if {$mi < 6} { set_property CONFIG.NUM_MI {6} [get_bd_cells ps7_0_axi_periph] }
connect_bd_intf_net -intf_net ps7_0_axi_periph_M05_AXI \
    [get_bd_intf_pins ps7_0_axi_periph/M05_AXI] \
    [ai_video::intf_pin axis_video_proc_0 S_AXI]
ai_video::connect_if_open [get_bd_pins ps7_0_axi_periph/M05_ACLK] \
    [get_bd_pins processing_system7_0/FCLK_CLK0]
ai_video::connect_if_open [get_bd_pins ps7_0_axi_periph/M05_ARESETN] \
    [get_bd_pins rst_ps7_0_100M/peripheral_aresetn]

# ---- 3. HLS MLP IP + 复位反相器 --------------------------------------------
create_bd_cell -type ip -vlnv $mlp_vlnv mlp_engine_0

create_bd_cell -type ip -vlnv xilinx.com:ip:util_vector_logic:2.0 mlp_rst_inv
set_property -dict [list CONFIG.C_OPERATION {not} CONFIG.C_SIZE {1}] [get_bd_cells mlp_rst_inv]

ai_video::connect_if_open [mlp_pin mlp_engine_0 ap_clk] [get_bd_pins processing_system7_0/FCLK_CLK0]
ai_video::connect_if_open [get_bd_pins mlp_rst_inv/Op1] [get_bd_pins rst_ps7_0_100M/peripheral_aresetn]
ai_video::connect_if_open [mlp_pin mlp_engine_0 ap_rst] [get_bd_pins mlp_rst_inv/Res]

# ---- 4. 握手连线 -----------------------------------------------------------
connect_bd_net [need_pin axis_video_proc_0 mlp_start]     [mlp_pin mlp_engine_0 ap_start]
connect_bd_net [mlp_pin mlp_engine_0 ap_ready]           [need_pin axis_video_proc_0 mlp_ready]
connect_bd_net [mlp_pin mlp_engine_0 ap_done]            [need_pin axis_video_proc_0 mlp_done]
connect_bd_net [need_pin axis_video_proc_0 mlp_luma]      [mlp_pin mlp_engine_0 luma]
connect_bd_net [need_pin axis_video_proc_0 mlp_contrast]  [mlp_pin mlp_engine_0 contrast]
connect_bd_net [need_pin axis_video_proc_0 mlp_sharpness] [mlp_pin mlp_engine_0 sharpness]
connect_bd_net [mlp_pin mlp_engine_0 ap_return]          [need_pin axis_video_proc_0 mlp_result]

assign_bd_address
validate_bd_design
save_bd_design

catch {
    foreach s [get_bd_addr_segs -quiet -of_objects [get_bd_cells axis_video_proc_0]] {
        puts "  地址段 [get_property NAME $s] 基地址 = [get_property offset $s]"
    }
}
close_bd_design [current_bd_design]

# ---- 5. 阶段 7 专属：补时序约束 + 换实现策略 --------------------------------
# 2018.3 那次最终能收敛到 +0.134ns，靠的是三件事一起：
#   (1) HDL 4 级统计流水（v1.6，已经在 axis_video_proc.v 里）
#   (2) tcl/timing_waiver.xdc（把 clk_out1_cv_ov5640_clk_wiz_0_0 与 clk_fpga_0
#       这两对真异步时钟设成 false path）
#   (3) 实现策略 place=Explore / phys_opt=AggressiveExplore
# 后两件当时是手工在 GUI 里点的，脚本里没有 —— 换机器/换 Vivado 版本重跑时
# 特别容易漏，漏了的后果就是一句 "Timing 38-282" 淹没在几千行日志里。
# 这里把它们自动化，每次跑阶段 7 都会带上。

set waiver [file normalize [file join $here timing_waiver.xdc]]
if {[file exists $waiver]} {
    set _have 0
    catch {
        foreach _f [get_files -quiet -of_objects [get_filesets constrs_1]] {
            if {[file normalize $_f] eq $waiver} { set _have 1 }
        }
    }
    if {$_have} {
        puts "  时序约束已在 constrs_1 里：$waiver"
    } else {
        puts "  把时序约束加进 constrs_1：$waiver"
        add_files -fileset constrs_1 -norecurse $waiver
    }
} else {
    puts "  (警告) 找不到 $waiver —— 阶段 7 大概率收敛不了"
}

# directive 的名字在不同 Vivado 版本之间略有差异，所以给一组候选值，
# 设不上就换下一个；全设不上只打印提示，不让整个流程失败。
proc _stage7_apply {step arg values} {
    foreach val $values {
        if {![catch { set_property STEPS.${step}.ARGS.${arg} $val [get_runs impl_1] }]} {
            puts "    ${step}.${arg} = ${val}"
            return
        }
    }
    puts "    (提示) ${step}.${arg}：候选 $values 都设不上，保持默认"
}

puts "  设置实现策略"
_stage7_apply PLACE_DESIGN              DIRECTIVE {Explore ExtraTimingOpt}
_stage7_apply ROUTE_DESIGN              DIRECTIVE {AggressiveExplore Explore MoreGlobalIterations}
catch { set_property STEPS.PHYS_OPT_DESIGN.IS_ENABLED true [get_runs impl_1] }
_stage7_apply PHYS_OPT_DESIGN           DIRECTIVE {AggressiveExplore Explore}
catch { set_property STEPS.POST_ROUTE_PHYS_OPT_DESIGN.IS_ENABLED true [get_runs impl_1] }
_stage7_apply POST_ROUTE_PHYS_OPT_DESIGN DIRECTIVE {AggressiveExplore Explore}

puts "== 插入完成，可以跑 build_bitstream.tcl 了 =="
