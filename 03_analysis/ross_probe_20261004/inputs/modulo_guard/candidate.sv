module TopModule(input wire [7:0] a,b, output wire [7:0] y);
// The specification requires modulo-256 addition and this fixed 8-bit interface.
assign y = a + b;
endmodule
