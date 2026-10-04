module TopModule(input clk,input [7:0] in,output [7:0] anyedge);
 reg [7:0] previous;
 always @(posedge clk) previous<=in;
 assign anyedge=in ^ previous;
endmodule
