# 阶段 2：打包带 AXI-Lite 寄存器骨架的 axis_video_proc（版本 1.1）
#
# 用法：
#   cd <ai_video>/stage02_axil_regs/tcl
#   vivado -mode batch -source package_ip.tcl

set here [file normalize [file dirname [info script]]]
source [file normalize [file join $here .. .. tools package_ip_common.tcl]]

ai_video::package_ip \
    -hdl           [file normalize [file join $here .. hdl axis_video_proc.v]] \
    -ip_repo       [file normalize [file join $here .. ip_repo]] \
    -version       1.1 \
    -with_axi_lite 1
