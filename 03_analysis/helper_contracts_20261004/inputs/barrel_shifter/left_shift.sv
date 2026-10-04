module TopModule(input [7:0] in,input [2:0] ctrl,output [7:0] out);assign out=in<<ctrl;endmodule
