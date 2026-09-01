puts "RTL_EVAL_ARGC=$argc ARGV=$argv"
if {$argc != 2} {
    puts stderr "ERROR: expected source_file and output_dir, got $argc arguments"
    exit 1
}
set source_file [string map {\\ /} [lindex $argv 0]]
set output_dir [string map {\\ /} [lindex $argv 1]]
puts "RTL_EVAL_SOURCE=$source_file OUTPUT=$output_dir"
set target_part "xczu3eg-sbva484-1-e"

file mkdir $output_dir
set rc [catch {
    set available [get_parts -quiet $target_part]
    if {[llength $available] != 1} {
        error "required target part $target_part is not installed"
    }
    read_verilog -sv $source_file
    synth_design -top TopModule -part $target_part
    if {[llength [get_ports -quiet clk]] == 1} {
        create_clock -name clk -period 5.000 [get_ports clk]
    }
    write_checkpoint -force [file join $output_dir post_synth.dcp]
    report_utilization -file [file join $output_dir utilization.rpt]
    report_timing_summary -file [file join $output_dir timing.rpt]
    set fp [open [file join $output_dir PASS] w]
    puts $fp "part=$target_part"
    puts $fp "clock_period_ns=5.000"
    close $fp
} message options]

if {$rc != 0} {
    puts stderr "ERROR: $message"
    if {[dict exists $options -errorinfo]} {
        puts stderr [dict get $options -errorinfo]
    }
    exit 1
}
puts "RTL_SYNTHESIS_PASS part=$target_part clock_period_ns=5.000"
exit 0
