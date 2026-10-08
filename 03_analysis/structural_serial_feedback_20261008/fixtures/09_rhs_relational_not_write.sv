module Circuit(input clk, input a, output reg q, output reg r);
always @* r=(q <= a);
always @(posedge clk) q<=a;
endmodule
