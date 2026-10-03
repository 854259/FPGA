// Deliberately wrong: unsigned carry is not signed overflow.
module TopModule(input [7:0] a, b, output [7:0] s, output overflow);
  wire [8:0] total = {1'b0, a} + {1'b0, b};
  assign s = total[7:0];
  assign overflow = total[8];
endmodule
