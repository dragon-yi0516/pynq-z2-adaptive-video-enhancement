# 阶段 1：把纯直通版 axis_video_proc 插进 BD（没有 AXI-Lite）
#
# 用法：
#   cd <Pynq_CV_OV5640_master>/boards/Pynq-Z2/ov5640/bitstream
#   vivado -mode batch -source cv_ov5640.tcl -notrace
#   vivado -mode batch -source <ai_video>/stage01_axis_passthrough/tcl/insert_axis_video_proc.tcl -notrace
#   vivado -mode batch -source build_bitstream.tcl -notrace

set here [file normalize [file dirname [info script]]]
source [file normalize [file join $here .. .. tools insert_axis_video_proc_common.tcl]]

ai_video::insert_proc \
    -vlnv           "user.org:user:axis_video_proc:1.0" \
    -ip_repo        [file normalize [file join $here .. ip_repo]] \
    -with_axi_lite  0
