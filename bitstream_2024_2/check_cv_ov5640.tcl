################################################################
# Vivado 2024.2 - 检查实现后的时序是否收敛
################################################################
set overlay_name "cv_ov5640"
set design_name  "cv_ov5640"

cd [file dirname [info script]]

set rpt "./${overlay_name}/${overlay_name}.runs/impl_1/${design_name}_wrapper_timing_summary_routed.rpt"
if { ![file exists $rpt] } {
   puts "ERROR: 找不到时序报告 $rpt，请先运行 build_bitstream.tcl"
   exit 1
}

set fd [open $rpt r]
set timing_met 0
while { [gets $fd line] >= 0 } {
   if { [string match {All user specified timing constraints are met.} $line] } {
      set timing_met 1
      break
   }
}
close $fd

if { $timing_met == 0 } {
   puts "ERROR: ${overlay_name} 比特流生成未满足时序约束。"
   exit 1
}
puts "Timing constraints are met."

