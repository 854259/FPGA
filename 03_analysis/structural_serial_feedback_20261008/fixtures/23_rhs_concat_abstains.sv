module Circuit(input clk, input a, output reg q);
reg [1:0] r;
always @* begin q=a; r={a,q}; end
always @(posedge clk) q<=a;
endmodule
