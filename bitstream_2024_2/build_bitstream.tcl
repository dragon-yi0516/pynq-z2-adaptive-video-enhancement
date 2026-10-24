################################################################
# Vivado 2024.2
# 综合 / 实现 / 生成比特流，并导出 PYNQ 需要的 .bit 与 .hwh
################################################################
set overlay_name "cv_ov5640"
set design_name  "cv_ov5640"

# 想改并行度：export VIVADO_JOBS=8
set jobs 4
if { [info exists ::env(VIVADO_JOBS)] } {
   set jobs $::env(VIVADO_JOBS)
}

# 始终以本脚本所在目录为工作目录
cd [file dirname [info script]]

# 打开由 cv_ov5640.tcl 创建好的工程
open_project ./${overlay_name}/${overlay_name}.xpr
open_bd_design ./${overlay_name}/${overlay_name}.srcs/sources_1/bd/${design_name}/${design_name}.bd

# 把 Block Design 的 wrapper 设为顶层
make_wrapper -files [get_files ./${overlay_name}/${overlay_name}.srcs/sources_1/bd/${design_name}/${design_name}.bd] -top
add_files -norecurse ./${overlay_name}/${overlay_name}.srcs/sources_1/bd/${design_name}/hdl/${design_name}_wrapper.v
set_property top ${design_name}_wrapper [current_fileset]
update_compile_order -fileset sources_1

# 综合 -> 实现 -> 比特流
launch_runs impl_1 -to_step write_bitstream -jobs $jobs
wait_on_run impl_1

set impl_status [get_property STATUS [get_runs impl_1]]
puts "INFO: impl_1 status = $impl_status"
if { [string first "Complete" $impl_status] == -1 } {
   error "ERROR: implementation did not complete (status = $impl_status)"
}

# 导出 PYNQ overlay 需要的两个文件
file copy -force ./${overlay_name}/${overlay_name}.runs/impl_1/${design_name}_wrapper.bit ${overlay_name}.bit
file copy -force ./${overlay_name}/${overlay_name}.srcs/sources_1/bd/${design_name}/hw_handoff/${design_name}.hwh ${overlay_name}.hwh

# 可选：Vitis 需要的话可以生成固定硬件平台（PYNQ 不需要）
# write_hw_platform -fixed -include_bit -force ./${overlay_name}.xsa

puts "INFO: wrote ${overlay_name}.bit and ${overlay_name}.hwh in [pwd]"

