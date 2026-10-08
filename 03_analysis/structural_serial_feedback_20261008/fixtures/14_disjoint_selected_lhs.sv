module Circuit(input clk, input a, output reg [1:0] q);
always @* q[0]=a;
always @(posedge clk) q[1]<=a;
endmodule
