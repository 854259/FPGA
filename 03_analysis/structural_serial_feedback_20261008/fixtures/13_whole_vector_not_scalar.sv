module Circuit(input clk, input [7:0] a, output reg [7:0] q);
always @* q=a;
always @(posedge clk) q<=0;
endmodule
