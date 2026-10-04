`timescale 1ns/1ps
module R2Probe;
reg a,b,c,d; wire out;
TopModule _mapcheck_dut(.a(a),.b(b),.c(c),.d(d),.out(out));
integer _mapcheck_checks=0,_mapcheck_mismatches=0;
initial begin
a=1'b0; b=1'b0; c=1'b0; d=1'b0; #1;
_mapcheck_checks=_mapcheck_checks+1; if (out !== 1'b1) begin
if(_mapcheck_mismatches==0) $display("MAP_FIRST inputs=a=0,b=0,c=0,d=0 expected=1 observed=%b",out);
_mapcheck_mismatches=_mapcheck_mismatches+1;end
a=1'b0; b=1'b0; c=1'b0; d=1'b1; #1;
_mapcheck_checks=_mapcheck_checks+1; if (out !== 1'b1) begin
if(_mapcheck_mismatches==0) $display("MAP_FIRST inputs=a=0,b=0,c=0,d=1 expected=1 observed=%b",out);
_mapcheck_mismatches=_mapcheck_mismatches+1;end
a=1'b0; b=1'b0; c=1'b1; d=1'b0; #1;
_mapcheck_checks=_mapcheck_checks+1; if (out !== 1'b1) begin
if(_mapcheck_mismatches==0) $display("MAP_FIRST inputs=a=0,b=0,c=1,d=0 expected=1 observed=%b",out);
_mapcheck_mismatches=_mapcheck_mismatches+1;end
a=1'b0; b=1'b0; c=1'b1; d=1'b1; #1;
_mapcheck_checks=_mapcheck_checks+1; if (out !== 1'b0) begin
if(_mapcheck_mismatches==0) $display("MAP_FIRST inputs=a=0,b=0,c=1,d=1 expected=0 observed=%b",out);
_mapcheck_mismatches=_mapcheck_mismatches+1;end
a=1'b0; b=1'b1; c=1'b0; d=1'b0; #1;
_mapcheck_checks=_mapcheck_checks+1; if (out !== 1'b1) begin
if(_mapcheck_mismatches==0) $display("MAP_FIRST inputs=a=0,b=1,c=0,d=0 expected=1 observed=%b",out);
_mapcheck_mismatches=_mapcheck_mismatches+1;end
a=1'b0; b=1'b1; c=1'b0; d=1'b1; #1;
_mapcheck_checks=_mapcheck_checks+1; if (out !== 1'b0) begin
if(_mapcheck_mismatches==0) $display("MAP_FIRST inputs=a=0,b=1,c=0,d=1 expected=0 observed=%b",out);
_mapcheck_mismatches=_mapcheck_mismatches+1;end
a=1'b0; b=1'b1; c=1'b1; d=1'b0; #1;
_mapcheck_checks=_mapcheck_checks+1; if (out !== 1'b1) begin
if(_mapcheck_mismatches==0) $display("MAP_FIRST inputs=a=0,b=1,c=1,d=0 expected=1 observed=%b",out);
_mapcheck_mismatches=_mapcheck_mismatches+1;end
a=1'b0; b=1'b1; c=1'b1; d=1'b1; #1;
_mapcheck_checks=_mapcheck_checks+1; if (out !== 1'b1) begin
if(_mapcheck_mismatches==0) $display("MAP_FIRST inputs=a=0,b=1,c=1,d=1 expected=1 observed=%b",out);
_mapcheck_mismatches=_mapcheck_mismatches+1;end
a=1'b1; b=1'b0; c=1'b0; d=1'b0; #1;
_mapcheck_checks=_mapcheck_checks+1; if (out !== 1'b1) begin
if(_mapcheck_mismatches==0) $display("MAP_FIRST inputs=a=1,b=0,c=0,d=0 expected=1 observed=%b",out);
_mapcheck_mismatches=_mapcheck_mismatches+1;end
a=1'b1; b=1'b0; c=1'b0; d=1'b1; #1;
_mapcheck_checks=_mapcheck_checks+1; if (out !== 1'b1) begin
if(_mapcheck_mismatches==0) $display("MAP_FIRST inputs=a=1,b=0,c=0,d=1 expected=1 observed=%b",out);
_mapcheck_mismatches=_mapcheck_mismatches+1;end
a=1'b1; b=1'b0; c=1'b1; d=1'b0; #1;
_mapcheck_checks=_mapcheck_checks+1; if (out !== 1'b0) begin
if(_mapcheck_mismatches==0) $display("MAP_FIRST inputs=a=1,b=0,c=1,d=0 expected=0 observed=%b",out);
_mapcheck_mismatches=_mapcheck_mismatches+1;end
a=1'b1; b=1'b0; c=1'b1; d=1'b1; #1;
_mapcheck_checks=_mapcheck_checks+1; if (out !== 1'b1) begin
if(_mapcheck_mismatches==0) $display("MAP_FIRST inputs=a=1,b=0,c=1,d=1 expected=1 observed=%b",out);
_mapcheck_mismatches=_mapcheck_mismatches+1;end
a=1'b1; b=1'b1; c=1'b0; d=1'b0; #1;
_mapcheck_checks=_mapcheck_checks+1; if (out !== 1'b0) begin
if(_mapcheck_mismatches==0) $display("MAP_FIRST inputs=a=1,b=1,c=0,d=0 expected=0 observed=%b",out);
_mapcheck_mismatches=_mapcheck_mismatches+1;end
a=1'b1; b=1'b1; c=1'b0; d=1'b1; #1;
_mapcheck_checks=_mapcheck_checks+1; if (out !== 1'b0) begin
if(_mapcheck_mismatches==0) $display("MAP_FIRST inputs=a=1,b=1,c=0,d=1 expected=0 observed=%b",out);
_mapcheck_mismatches=_mapcheck_mismatches+1;end
a=1'b1; b=1'b1; c=1'b1; d=1'b0; #1;
_mapcheck_checks=_mapcheck_checks+1; if (out !== 1'b0) begin
if(_mapcheck_mismatches==0) $display("MAP_FIRST inputs=a=1,b=1,c=1,d=0 expected=0 observed=%b",out);
_mapcheck_mismatches=_mapcheck_mismatches+1;end
a=1'b1; b=1'b1; c=1'b1; d=1'b1; #1;
_mapcheck_checks=_mapcheck_checks+1; if (out !== 1'b1) begin
if(_mapcheck_mismatches==0) $display("MAP_FIRST inputs=a=1,b=1,c=1,d=1 expected=1 observed=%b",out);
_mapcheck_mismatches=_mapcheck_mismatches+1;end
$display("R2_PROBE_RESULT task=Prob057_kmap2 checks=%0d mismatches=%0d",_mapcheck_checks,_mapcheck_mismatches);
if(_mapcheck_checks!=16) $fatal(1,"CHECK_COUNT_INVALID");$finish;end
initial begin #1000;$fatal(1,"WATCHDOG_EXPIRED");end
endmodule
