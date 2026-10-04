module TopModule(input [7:0] A,B,output reg [15:0] product);
integer i;always @* begin product=0;for(i=0;i<8;i=i+1)if(B[i])product=product+({8'b0,A}<<i);end endmodule
