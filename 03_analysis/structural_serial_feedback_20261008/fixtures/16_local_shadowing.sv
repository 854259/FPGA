module Circuit(input clk, input a, output reg q);
always @* begin reg q; q=a; end
always @(posedge clk) q<=a;
endmodule
