`timescale 1ns/1ps
module R2Probe;
 reg clk=0; reg [7:0] in=0; wire [7:0] anyedge;
 TopModule dut(.clk(clk),.in(in),.anyedge(anyedge));
 integer checks=0, mismatches=0, i; reg [31:0] rng=32'h439fab12;
 reg [7:0] history=0, held=0, value;
 task check(input [7:0] expected);
 begin checks=checks+1; if (anyedge !== expected) mismatches=mismatches+1; end endtask
 initial begin
  // Two sampled zeros establish history without constraining unspecified startup.
  #2; clk=1; #2; clk=0; #2; clk=1; #2; clk=0; #2;
  for (i=0;i<128;i=i+1) begin
   rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
   case(i) 0:value=0; 1:value=255; 2:value=255; 3:value=0;
    4:value=85; 5:value=170; 6:value=128; 7:value=1; default:value=rng[7:0]; endcase
   in=~value; #1; check(held);
   in=value; #1; check(held);
   held=value ^ history; history=value;
   clk=1; #1; check(held); clk=0; #1; check(held);
  end
  $display("R2_PROBE_RESULT task=Prob045_edgedetect2 checks=%0d mismatches=%0d",checks,mismatches); $finish;
 end
endmodule
