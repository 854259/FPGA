// Deliberately wrong: parity keeps only the low bit of the population count.
module TopModule(input [2:0] in, output [1:0] out);
  assign out = {1'b0, ^in};
endmodule
