module Circuit(input clk, input a, output reg q, output reg r);
always @* r=a;
always @(posedge clk) q<=a;
endmodule
