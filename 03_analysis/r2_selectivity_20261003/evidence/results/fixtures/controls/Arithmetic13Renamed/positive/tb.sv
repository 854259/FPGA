`timescale 1ns/1ps
module R2Probe;
 reg c=0,l=0,e=0; reg [12:0] d=0; wire [12:0] y;
 integer expected=0, old_value=0, checks=0, mismatches=0, i;
 TopModule dut(.tick(c),.put(l),.move(e),.word_in(d),.word_out(y));
 task step(input integer ld,input integer en,input integer value);
 begin
  c=0; #2; l=ld; e=en; d=value;
  if(ld) expected=value & 8191;
  else if(en) begin
   old_value=expected; expected=old_value/2;
   if(1 && old_value>=4096) expected=expected+4096;
  end
  #2; c=1; #1; checks=checks+1;
  if(y !== expected[12:0]) begin mismatches=mismatches+1;
   $display("FIXTURE_MISMATCH n=%0d got=%h expected=%h",checks,y,expected[12:0]); end
  #1; c=0;
 end endtask
 initial begin
  step(1,0,4096); step(0,1,0); step(0,1,0); step(0,0,0);
  step(1,1,8191); step(0,1,0); step(0,1,0);
  step(1,0,4095); step(0,1,0); step(0,0,0);
  step(1,0,0); step(0,1,0);
  step(1,0,4101);
  for(i=0;i<5;i=i+1) step(0,1,0);
  $display("R2_PROBE_RESULT task=Arithmetic13Renamed checks=%0d mismatches=%0d",checks,mismatches);
  $finish;
 end
endmodule
