# 阶段 12：打包「连续参数 + 四象限统计」版 axis_video_proc（版本 1.9）
#
# 版本号为什么是 1.9：
#   1.0/1.1/1.2(stage01/02/03)、1.7(stage03 修订)、1.3/1.4(stage06)、1.6(stage07)
#   都被占了；几个阶段的 ip_repo 会同时挂进同一个工程，同 VLNV 不同内容会打架。
#   1.8 = 修订 01（第一次综合 WNS -3.798，违例）
#   1.9 = 修订 02（像素通路拆成 A/B 两级流水，修时序）
#   版本号必须跟着 HDL 一起涨，否则工程可能继续用缓存里那份旧 IP。
#
# 相对阶段 7（1.6）的差别：
#   * 新增 PARAM 寄存器（0x34）：三种处理的强度从「固定」改成「连续可调」
#   * 新增四象限亮度统计（0x38 / 0x3C）：算空间不均匀度，区分整体亮 / 局部亮
#   * 数据通路结构没动（还是 px1_* 两级流水 + 3 级统计流水）
#
# 用法：
#   cd <ai_video>/stage12_adaptive/tcl
#   vivado -mode batch -source package_ip.tcl

set here [file normalize [file dirname [info script]]]
source [file normalize [file join $here .. .. tools package_ip_common.tcl]]

ai_video::package_ip \
    -hdl           [file normalize [file join $here .. hdl axis_video_proc.v]] \
    -ip_repo       [file normalize [file join $here .. ip_repo]] \
    -version       2.0 \
    -with_axi_lite 1
