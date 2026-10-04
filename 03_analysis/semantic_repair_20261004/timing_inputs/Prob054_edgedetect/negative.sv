module TopModule(input clk,input [7:0] in,output [7:0] pedge);
 reg [7:0] previous;
 always @(posedge clk) previous<=in;
 assign pedge=in & ~previous;
endmodule
