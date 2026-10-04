module TopModule(input [7:0] A,B,output reg [15:0] product);
always @* product=(A*B)&16'h00ff;endmodule
