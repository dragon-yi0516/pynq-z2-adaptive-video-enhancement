# 阶段 1：把纯直通版 axis_video_proc.v 打包成 IP（版本 1.0，没有 AXI-Lite）
#
# 用法：
#   cd <ai_video>/stage01_axis_passthrough/tcl
#   vivado -mode batch -source package_ip.tcl
#
# 真正的打包逻辑在 ../../tools/package_ip_common.tcl（各阶段共用一份接口定义，
# 避免不同阶段打包出来的接口不一致）。

set here [file normalize [file dirname [info script]]]
source [file normalize [file join $here .. .. tools package_ip_common.tcl]]

ai_video::package_ip \
    -hdl           [file normalize [file join $here .. hdl axis_video_proc.v]] \
    -ip_repo       [file normalize [file join $here .. ip_repo]] \
    -version       1.0 \
    -with_axi_lite 0
