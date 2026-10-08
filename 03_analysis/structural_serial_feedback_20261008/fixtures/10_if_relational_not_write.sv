module Circuit(input clk, input a, output reg q, output reg r);
always @* begin if(q <= a) r=1; else r=0; end
always @(posedge clk) q<=a;
endmodule
