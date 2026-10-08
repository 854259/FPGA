module Circuit(input clk, input a, output reg q);
always @* q=#1 a;
always @(posedge clk) q<=a;
endmodule
