module TopModule(input [7:0] a, b, output [7:0] s, output overflow);
  wire signed [8:0] extended_a = {a[7], a};
  wire signed [8:0] extended_b = {b[7], b};
  wire signed [8:0] total = extended_a + extended_b;
  assign s = total[7:0];
  assign overflow = total[8] ^ total[7];
endmodule
