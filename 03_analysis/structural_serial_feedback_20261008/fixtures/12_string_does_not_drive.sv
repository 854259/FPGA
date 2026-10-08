module Circuit(input clk, input a, output reg q);
localparam MESSAGE="always @(*) q=0; endmodule";
always @(posedge clk) q<=a;
endmodule
