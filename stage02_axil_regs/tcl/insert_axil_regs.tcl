# 阶段 2：把带 AXI-Lite 的 axis_video_proc 插进 BD 并挂到 AXI 互联
#
# 用法：
#   cd <Pynq_CV_OV5640_master>/boards/Pynq-Z2/ov5640/bitstream
#   vivado -mode batch -source cv_ov5640.tcl -notrace
#   vivado -mode batch -source <ai_video>/stage02_axil_regs/tcl/insert_axil_regs.tcl -notrace
#   vivado -mode batch -source build_bitstream.tcl -notrace

set here [file normalize [file dirname [info script]]]
source [file normalize [file join $here .. .. tools insert_axis_video_proc_common.tcl]]

ai_video::insert_proc \
    -vlnv           "user.org:user:axis_video_proc:1.1" \
    -ip_repo        [file normalize [file join $here .. ip_repo]] \
    -with_axi_lite  1
