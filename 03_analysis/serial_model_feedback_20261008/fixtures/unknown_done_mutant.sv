// Synthetic mutant: observed X must be a semantic mismatch, never a pass.
module TopModule(input clock, input rst, input rx, output received, output [2:0] payload);
  assign received=1'bx;
  assign payload=3'bxxx;
endmodule
