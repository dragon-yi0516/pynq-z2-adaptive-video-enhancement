# =============================================================================
# 时序约束补丁 v2（2026-10-04 晚）—— 附 v1 失败的原因
#
# 【v1 为什么没生效】
#  v1 用的是 set_clock_groups -asynchronous -group ...vid_pclk，结果 WNS 还是 -4.0。
#  原因是：视频侧那条时钟链**不是**从顶层端口 vid_pclk 派生出来的 ——
#  BD 里 clk_wiz 这个 IP 自带一条约束（cv_ov5640_clk_wiz_0_0.xdc 第 56 行）：
#        create_clock -period 10.000 [get_ports clk_in1]
#  所以全局设计里 clk_out1_cv_ov5640_clk_wiz_0_0 的源时钟是那条 clk_in1，
#  不是新写的 vid_pclk —— `-include_generated_clocks vid_pclk` 带不上 clk_out1，
#  那两条跨域路径照旧按单周期检查，WNS 依旧是 -4.0。
#
#  （顺带发现这条 IP 自带约束本身也不准：它把摄像头像素时钟写成 10 ns / 100 MHz，
#    实际是 13.468 ns / 74.25 MHz。属原始开源工程的历史遗留，先不动它。
#    这也解释了 v1 里 TNS 从 -11.250 变成 -12.605：补了 create_clock vid_pclk
#    之后，原来"不检查"的 152 个寄存器开始被检查了。）
#
# 【v2 的做法】只掐真正在失败的那两对时钟，不依赖任何生成时钟关系
#  （timing_final.rpt 里 async_default 组只有这两对是负的）：
#        clk_out1_cv_ov5640_clk_wiz_0_0 → clk_fpga_0   -4.044
#        clk_fpga_0 → clk_out1_cv_ov5640_clk_wiz_0_0   -3.603
#
# 【加之前请先确认】这两对之间没有真正需要单周期检查的路径
#  （正常应该都在 Xilinx IP 的异步 FIFO / 复位同步器里）：
#
#    report_timing -from [get_clocks clk_out1_cv_ov5640_clk_wiz_0_0] \
#                   -to [get_clocks clk_fpga_0] \
#                   -max_paths 200 -nworst 200 -sort_by_slack -file /home/xu/cross_A.rpt
#    report_timing -from [get_clocks clk_fpga_0] \
#                   -to [get_clocks clk_out1_cv_ov5640_clk_wiz_0_0] \
#                   -max_paths 200 -nworst 200 -sort_by_slack -file /home/xu/cross_B.rpt
#    grep -c axis_video_proc /home/xu/cross_A.rpt /home/xu/cross_B.rpt   # 两个都要是 0
#
# 【用法】
#   1) 把工程里 v1 那份删掉（或直接用本文件覆盖它的内容），再加进 constrs_1；
#   2) reset_run impl_1 → launch_runs impl_1 -to_step write_bitstream -jobs 4
#   3) report_timing_summary -file /home/xu/timing_v2.rpt
#      期望看到 `All user specified timing constraints are met`
#      （剩下最好的 slack 应该是 clk_fpga_0 域的 +0.119）
# =============================================================================

# 只掐这两对（时钟名与 timing_final.rpt 里的完全一致）
set_false_path -from [get_clocks -quiet clk_out1_cv_ov5640_clk_wiz_0_0] \
               -to   [get_clocks -quiet clk_fpga_0]
set_false_path -from [get_clocks -quiet clk_fpga_0] \
               -to   [get_clocks -quiet clk_out1_cv_ov5640_clk_wiz_0_0]

# ---------------------------------------------------------------------------
# 可选、这次先别开：顶层确实缺摄像头像素时钟的 create_clock
# （BD 的 OOC 文件 cv_ov5640_ooc.xdc 里有，但那份不参与顶层流程，
#   所以报告里才有「152 个寄存器 no_clock: vid_pclk」）。
# 补上它之后原先"不检查"的 152 个寄存器会开始按 13.468 ns 检查，
# 可能冒出新的违例。等这次报告干净了再单独评估。
#
# create_clock -name vid_pclk -period 13.468 [get_ports vid_pclk]
#
# 板级接口的输入/输出延迟（报告里的 12 输入 / 6 输出 no_*_delay）同理，
# 要查 OV5640 数据手册的 tSU/tHD 才能给准，属于已知项，不影响验收。
# ---------------------------------------------------------------------------
