`timescale 1ns/1ps
module R2Probe;
 reg clk=0,reset=1,in=0; wire disc,flag,err;
 TopModule dut(.clk(clk),.reset(reset),.in(in),.disc(disc),.flag(flag),.err(err));
 integer checks=0,mismatches=0,count=0,i,n; reg value; reg [2:0] held=0;
 reg [31:0] rng=32'h138af902;
 task check;
 begin checks=checks+1; if({disc,flag,err} !== held) mismatches=mismatches+1; end endtask
 task step(input sample,input rst);
 begin
  reset=rst; in=~sample; #1; check; in=sample; #1; check;
  if(rst) begin count=0; held=0; end
  else begin
   held[2]=(count==5 && !sample); held[1]=(count==6 && !sample);
   if(sample) begin if(count<7) count=count+1; end else count=0;
   held[0]=(count==7);
  end
  clk=1; #1; check; clk=0; #1; check;
 end endtask
 initial begin
  // Establish the specified synchronous reset before inspecting outputs.
  #1; clk=1; #1; clk=0; #1; reset=0;
  for(n=0;n<10;n=n+1) begin
   step(0,0); for(i=0;i<n;i=i+1) step(1,0); step(0,0);
  end
  for(i=0;i<128;i=i+1) begin
   rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]}; step(rng[0],i%37==0);
  end
  $display("R2_PROBE_RESULT task=Prob140_fsm_hdlc checks=%0d mismatches=%0d",checks,mismatches); $finish;
 end
endmodule
