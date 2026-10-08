module Circuit(input clk, input a, output reg q);
// always @* q=0;
/* always @(posedge clk) q<=1; */
always @(posedge clk) q<=a;
endmodule
