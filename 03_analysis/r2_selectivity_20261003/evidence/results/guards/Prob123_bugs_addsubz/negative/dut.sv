// Deliberately wrong: test an untruncated 9-bit sum/difference for zero.
module TopModule(input do_sub, input [7:0] a, b,
                 output [7:0] out, output result_is_zero);
  wire [8:0] wide = do_sub ? {1'b0, a} - {1'b0, b} : {1'b0, a} + {1'b0, b};
  assign out = wide[7:0];
  assign result_is_zero = (wide == 9'b0);
endmodule
