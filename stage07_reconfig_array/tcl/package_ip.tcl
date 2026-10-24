# 阶段 7：打包带三模式重构阵列的 axis_video_proc（版本 1.6）
#
# 1.4 = 时序违例最严重（WNS -5.093）的初版
# 1.5 = 像素通路两级流水 + mode2 无符号算式（WNS -3.923，grad 路径仍违例）
# 1.6 = 统计链路再切一级（亮度/梯度分开，源头改成 px1_*）
# 版本号必须跟着 HDL 一起涨，否则工程里可能继续用旧的一份 IP。
#
# 用法：
#   cd <ai_video>/stage07_reconfig_array/tcl
#   vivado -mode batch -source package_ip.tcl

set here [file normalize [file dirname [info script]]]
source [file normalize [file join $here .. .. tools package_ip_common.tcl]]

ai_video::package_ip \
    -hdl           [file normalize [file join $here .. hdl axis_video_proc.v]] \
    -ip_repo       [file normalize [file join $here .. ip_repo]] \
    -version       1.6 \
    -with_axi_lite 1
