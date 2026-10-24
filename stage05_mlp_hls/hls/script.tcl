# =============================================================================
# Vitis HLS 建工程 + C 仿真 + 综合 + 导出 IP
#
# 用法（Vitis HLS 2024.2）：
#   cd <ai_video>/stage05_mlp_hls/hls
#   vitis_hls -f script.tcl        (2024.2 里 vivado_hls 已被 vitis_hls 取代)
#
# 前置：weights/mlp_weights.h 必须已经由阶段 4 生成，并拷到 ../src/ 下。
#       （05_mlp_verify.ipynb 会自动帮你拷 + 生成 tv_mlp.h）
#
# 产物：mlp_engine_prj/solution1/impl/ip/   —— 可被 Vivado 直接引用的 IP
# =============================================================================

set script_dir [file normalize [file dirname [info script]]]
set stage_dir  [file normalize [file join $script_dir ..]]
set src_dir    [file normalize [file join $stage_dir src]]
set prj_name   "mlp_engine_prj"
set prj_dir    [file normalize [file join $stage_dir $prj_name]]

set part_name "xc7z020clg400-1"
set top_name  "mlp_engine"

# 先确认测试向量和权重头文件都在。少了它们 HLS 会报一大堆看不懂的错，
# 不如在这里直接说清楚该先跑什么。
foreach need [list [file join $src_dir mlp_engine.cpp] \
                   [file join $src_dir mlp_engine_tb.cpp] \
                   [file join $src_dir mlp_weights.h] \
                   [file join $src_dir tv_mlp.h]] {
    if {![file exists $need]} {
        puts "!! 缺少文件: $need"
        if {[string match "*tv_mlp.h" $need] || [string match "*mlp_weights.h" $need]} {
            puts "   mlp_weights.h / tv_mlp.h 由阶段 4/5 生成，先跑其中一个："
            puts "     虚拟机里： python3 [file join $script_dir .. make_tv.py]"
            puts "     板子上  ： 05_mlp_verify.ipynb"
        }
        exit 1
    }
}

# ---- 一致性检查：tv_mlp.h 必须和 mlp_weights.h 是同一代 ---------------------
# 第一次就踩过这个坑：src/mlp_weights.h 已经是新权重，但 src/tv_mlp.h 还是用旧权重
# 生成的，csim 直接报 48 条 MISMATCH（全是 got=2 expect=1），看起来特别像 C 代码有 bug。
# make_tv.py 会把权重的 sha256 写进 tv_mlp.h，这里对一遍就能立刻定位。
set w_src  [file normalize [file join $src_dir mlp_weights.h]]
set tv_src [file normalize [file join $src_dir tv_mlp.h]]
set w_ref  [file normalize [file join $stage_dir .. weights mlp_weights.h]]

set fh [open $tv_src r]; set tv_text [read $fh]; close $fh
set want_sha ""
if {![regexp {AI_VIDEO_WEIGHTS_SHA256:\s*([0-9a-fA-F]+)} $tv_text -> want_sha]} {
    puts "!! src/tv_mlp.h 里没有权重指纹，说明它是旧版脚本生成的。"
    puts "   先重新生成： python3 [file join $stage_dir make_tv.py]"
    exit 1
}
set have_sha ""
catch { set have_sha [lindex [split [string trim [exec sha256sum $w_src]] " "] 0] }
if {$have_sha ne "" && ![string equal -nocase $want_sha $have_sha]} {
    puts ""
    puts "############################################################"
    puts "# tv_mlp.h 和 mlp_weights.h 不是同一代（权重指纹对不上）"
    puts "#   tv_mlp.h 里的指纹 : $want_sha"
    puts "#   src/mlp_weights.h : $have_sha"
    puts "# 这种组合下 csim 会报一堆 MISMATCH，但那不是 C 代码的问题。"
    puts "# 先重新生成（会同时刷新权重和测试向量）："
    puts "#   python3 [file join $stage_dir make_tv.py]"
    puts "############################################################"
    exit 1
}
if {[file exists $w_ref]} {
    set f1 [open $w_ref r]; set c1 [read $f1]; close $f1
    set f2 [open $w_src r]; set c2 [read $f2]; close $f2
    if {$c1 ne $c2} {
        puts ""
        puts "############################################################"
        puts "# src/mlp_weights.h 和 weights/mlp_weights.h 内容不一样"
        puts "# 说明 src/ 里那份不是最新的（板子上跑的是 weights/ 那份）。"
        puts "# 先重新生成： python3 [file join $stage_dir make_tv.py]"
        puts "############################################################"
        exit 1
    }
}
puts "== 一致性检查通过：tv_mlp.h 与 mlp_weights.h 是同一代 =="

puts "== 建立 HLS 工程 =="
# 注意：Vivado HLS 的 open_project 只认“项目名”，不接受带斜杠的绝对路径，
# 传绝对路径会直接报： ERROR: [HLS 200-70] The name '...' contains illegal character '/'
# 所以先切到 stage05_mlp_hls 目录，再用纯名字建工程。
# 这样工程落在 stage05_mlp_hls/mlp_engine_prj —— 正好是阶段 6 期望的位置。
cd $stage_dir
open_project -reset $prj_name
set_top $top_name
add_files [file join $src_dir mlp_engine.cpp]
add_files -tb [file join $src_dir mlp_engine_tb.cpp]

open_solution -reset "solution1"
set_part $part_name
# 100MHz，与工程里 FCLK_CLK0 一致；综合出来的 IP 不需要再做时钟适配
create_clock -period 10 -name default

puts "== C 仿真（必须通过：HLS 结果 == Python 定点参考） =="
if {[catch {csim_design} err]} {
    puts "CSIM FAILED: $err"
    exit 1
}

# 双保险：csim_design 在个别版本上不会因为测试台返回非 0 就报错，
# 所以再去 csim 的输出目录里找测试台自己打印的 "CSIM PASSED"。
set csim_dir [file join $prj_dir solution1 csim]
set passed 0
if {[catch {
    if {[llength [exec grep -rl "CSIM PASSED" $csim_dir]] > 0} { set passed 1 }
} e]} { set passed 0 }
if {!$passed} {
    puts ""
    puts "############################################################"
    puts "# CSIM 没有出现 'CSIM PASSED'，说明 HLS 结果和 Python 参考不一致"
    puts "# 去 $csim_dir 里翻日志，搜 MISMATCH 看是哪几条向量对不上"
    puts "############################################################"
    exit 1
}
puts "== CSIM 检查通过：HLS 与 Python 定点参考完全一致 =="

puts "== C 综合 =="
csynth_design

puts "== 导出 IP =="
export_design -rtl verilog -format ip_catalog \
    -vendor user.org -library user -version 1.0 \
    -description "ai_video MLP engine (3-8-3, Q8.8)"

puts "== 完成：IP 在 $prj_dir/solution1/impl/ip =="
exit
