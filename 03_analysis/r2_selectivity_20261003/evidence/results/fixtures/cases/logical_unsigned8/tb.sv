`timescale 1ns/1ps
module R2Probe;
 reg c=0,l=0,e=0; reg [7:0] d=0; wire [7:0] y;
 integer expected=0, old_value=0, checks=0, mismatches=0, i;
 TopModule dut(.clk(c),.load(l),.ena(e),.data(d),.q(y));
 task step(input integer ld,input integer en,input integer value);
 begin
  c=0; #2; l=ld; e=en; d=value;
  if(ld) expected=value & 255;
  else if(en) begin
   old_value=expected; expected=old_value/2;
   if(0 && old_value>=128) expected=expected+128;
  end
  #2; c=1; #1; checks=checks+1;
  if(y !== expected[7:0]) begin mismatches=mismatches+1;
   $display("FIXTURE_MISMATCH n=%0d got=%h expected=%h",checks,y,expected[7:0]); end
  #1; c=0;
 end endtask
 initial begin
  step(1,0,128); step(0,1,0); step(0,1,0); step(0,0,0);
  step(1,1,255); step(0,1,0); step(0,1,0);
  step(1,0,127); step(0,1,0); step(0,0,0);
  step(1,0,0); step(0,1,0);
  step(1,0,133);
  for(i=0;i<5;i=i+1) step(0,1,0);
  $display("R2_PROBE_RESULT task=Logical8 checks=%0d mismatches=%0d",checks,mismatches);
  $finish;
 end
endmodule
