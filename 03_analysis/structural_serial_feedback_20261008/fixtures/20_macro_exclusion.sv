module Circuit(input clk, input a, output reg q);
`ifdef CHOICE
always @* q=a;
`else
always @(posedge clk) q<=a;
`endif
endmodule
