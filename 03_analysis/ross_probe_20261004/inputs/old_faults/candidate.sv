module TopModule (
 input wire clk, input wire [3:0] sel, input wire [7:0] a,
 output reg [7:0] y, output wire [7:0] undriven_out, output reg [7:0] ovf
);
always @(*) begin if (sel == 1) y = a; end
always @(posedge clk) begin ovf <= a + 8'hFF; end
endmodule
