`timescale 1ns/1ps
module R2Probe;
 reg clk=0, aresetn=1, x=0; wire z;
 TopModule dut(.clk(clk),.aresetn(aresetn),.x(x),.z(z));
 integer checks=0,mismatches=0,state=0,i; reg value; reg [31:0] rng=32'h293a57b1;
 task check(input expected);
 begin checks=checks+1; if(z !== expected) mismatches=mismatches+1; end endtask
 initial begin
  #1; aresetn=0; #1; check(0); aresetn=1; #1; check(0);
  for(i=0;i<160;i=i+1) begin
   rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
   value=i<36 ? (i%3 != 1) : rng[0];
   x=~value; #1; check(state==2 && x);
   x=value; #1; check(state==2 && x);
   case(state) 0:state=x?1:0; 1:state=x?1:2; 2:state=x?1:0; endcase
   clk=1; #1; check(state==2 && x); clk=0; #1; check(state==2 && x);
  end
  $display("R2_PROBE_RESULT task=Prob129_ece241_2013_q8 checks=%0d mismatches=%0d",checks,mismatches); $finish;
 end
endmodule
