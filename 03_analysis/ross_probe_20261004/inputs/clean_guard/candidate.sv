module TopModule(input wire [7:0] a,b, input wire sel,
 output wire [7:0] y, output wire [7:0] bitxor);
assign y = sel ? a : b;
assign bitxor = a ^ b;
endmodule
