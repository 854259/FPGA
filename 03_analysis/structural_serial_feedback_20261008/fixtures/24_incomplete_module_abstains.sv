module Circuit(input clk, input a, output reg q);
always @* q=a;
always @(posedge clk) q<=a;
