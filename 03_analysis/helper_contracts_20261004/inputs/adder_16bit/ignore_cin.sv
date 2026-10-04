module TopModule(input [15:0] a,b,input Cin,output [15:0] y,output Co);assign {Co,y}={1'b0,a}+{1'b0,b};endmodule
