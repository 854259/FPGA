// Deliberately wrong: discard the required carry bit.
module TopModule(input [3:0] x, y, output [4:0] sum);
  wire [3:0] truncated = x + y;
  assign sum = {1'b0, truncated};
endmodule
