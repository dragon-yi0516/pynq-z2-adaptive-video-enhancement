# 阶段 6：打包带 MLP 握手的 axis_video_proc（版本 1.4）
#
# 修订历史：
#   1.3 = 原始版（统计链路没有流水线，和阶段 3 同样的时序问题）
#   1.4 = 统计链路加 4 级流水（源头改成 px1_*），修时序
#
# 用法：
#   cd <ai_video>/stage06_mlp_integrate/tcl
#   vivado -mode batch -source package_ip.tcl

set here [file normalize [file dirname [info script]]]
source [file normalize [file join $here .. .. tools package_ip_common.tcl]]

ai_video::package_ip \
    -hdl           [file normalize [file join $here .. hdl axis_video_proc.v]] \
    -ip_repo       [file normalize [file join $here .. ip_repo]] \
    -version       1.4 \
    -with_axi_lite 1
