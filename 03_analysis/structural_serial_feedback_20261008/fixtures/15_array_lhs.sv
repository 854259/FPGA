module Circuit(input clk, input a);
reg q[0:1];
always @* q[0]=a;
always @(posedge clk) q[1]<=a;
endmodule
