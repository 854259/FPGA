`timescale 1ns/1ps
module R2Probe;
reg [7:0] in;reg [2:0] ctrl;wire [7:0] out;TopModule dut(.in(in),.ctrl(ctrl),.out(out));
integer value,shift;integer checks=0,mismatches=0;reg [7:0] expected;
initial begin for(value=0;value<256;value=value+1)for(shift=0;shift<8;shift=shift+1)begin in=value;ctrl=shift;#1;expected=value>>shift;checks=checks+1;
if(out!==expected)begin if(mismatches==0)$display("FIRST_MISMATCH value=%h shift=%d observed=%h expected=%h",in,ctrl,out,expected);mismatches=mismatches+1;end end
$display("R2_PROBE_RESULT task=barrel_shifter checks=%0d mismatches=%0d",checks,mismatches);
if(checks!=2048)$fatal(1,"CHECK_COUNT_INVALID");$finish;end
initial begin #1000000;$fatal(1,"WATCHDOG_EXPIRED");end
endmodule
