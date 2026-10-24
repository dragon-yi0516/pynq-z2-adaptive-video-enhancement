# Export final implementation evidence for a completed Vivado project.
#
# Usage:
#   vivado -mode batch -nojournal -notrace \
#     -source tools/export_vivado_reports.tcl \
#     -tclargs /path/to/cv_ov5640.xpr /path/to/build/reports/stage13
#
# The design is not rebuilt. This script opens the existing implemented run
# and copies the source reports into a stable, submission-friendly location.

set xpr [lindex $argv 0]
set out_dir [lindex $argv 1]

if {$xpr eq ""} {
    error "Usage: -tclargs <project.xpr> \[output_dir\]"
}
set xpr [file normalize $xpr]
if {![file exists $xpr]} {
    error "Project not found: $xpr"
}
if {$out_dir eq ""} {
    set out_dir [file join [file dirname $xpr] reports_final]
}
set out_dir [file normalize $out_dir]
file mkdir $out_dir

puts "== Open project: $xpr"
open_project $xpr

set run_obj [get_runs impl_1]
set progress [get_property PROGRESS $run_obj]
set status [get_property STATUS $run_obj]
puts "== impl_1: PROGRESS=$progress STATUS=$status"
if {$progress ne "100%"} {
    error "impl_1 is not complete: PROGRESS=$progress STATUS=$status"
}

open_run impl_1
set design_name [get_property NAME [current_design]]
set timing_rpt [file join $out_dir timing_final.rpt]
set util_rpt   [file join $out_dir util_final.rpt]
set drc_rpt    [file join $out_dir drc_final.rpt]
set method_rpt [file join $out_dir methodology_final.rpt]
set source_rpt [file join $out_dir report_source.txt]

puts "== Report timing: $timing_rpt"
report_timing_summary -delay_type min_max -max_paths 10 -report_unconstrained \
    -file $timing_rpt

puts "== Report utilization: $util_rpt"
report_utilization -hierarchical -file $util_rpt

puts "== Report DRC: $drc_rpt"
report_drc -file $drc_rpt

puts "== Report methodology: $method_rpt"
report_methodology -file $method_rpt

set fd [open $source_rpt w]
puts $fd "project=$xpr"
puts $fd "impl_progress=$progress"
puts $fd "impl_status=$status"
puts $fd "design=$design_name"
puts $fd "tool_version=[version -short]"
puts $fd "generated=[clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
close $fd

puts "== Final reports written to: $out_dir"
puts "   timing_final.rpt"
puts "   util_final.rpt"
puts "   drc_final.rpt"
puts "   methodology_final.rpt"
puts "   report_source.txt"

close_design
close_project
