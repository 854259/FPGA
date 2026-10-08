module Circuit(input clk, input a, output reg q);
parameter CHOICE=1;
generate if(CHOICE) always @(posedge clk) q<=a; else always @(posedge clk) q<=0; endgenerate
endmodule
