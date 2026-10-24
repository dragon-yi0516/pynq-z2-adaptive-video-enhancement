# 阶段 3：打包带特征提取的 axis_video_proc（版本 1.7）
#
# 版本号为什么跳到 1.7 而不是 1.3：
#   1.3 已经被 stage06 用掉了（同一个 VLNV user.org:user:axis_video_proc），
#   1.6 是 stage07。几个阶段的 ip_repo 会同时挂进工程，
#   同 VLNV 不同内容会打架，所以只能往没人用过的号段跳。
#
# 修订历史：
#   1.2 = 原始版（统计链路没有流水线，100MHz 下 WNS 约 -5.4ns）
#   1.7 = 统计链路加 4 级流水（源头改成 px1_*），修时序
#
# 用法：
#   cd <ai_video>/stage03_feature_extract/tcl
#   vivado -mode batch -source package_ip.tcl

set here [file normalize [file dirname [info script]]]
source [file normalize [file join $here .. .. tools package_ip_common.tcl]]

ai_video::package_ip \
    -hdl           [file normalize [file join $here .. hdl axis_video_proc.v]] \
    -ip_repo       [file normalize [file join $here .. ip_repo]] \
    -version       1.7 \
    -with_axi_lite 1
