module Circuit(input clk, input a, output reg q);
always @(posedge clk) begin if(a) q<=1; else q<=0; if(q) q<=a; end
endmodule
