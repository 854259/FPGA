module TopModule(input [2:0] A,B, output A_greater,A_equal,A_less);
assign A_greater=(A[1:0]>B[1:0]); assign A_equal=(A[1:0]==B[1:0]); assign A_less=(A[1:0]<B[1:0]);
endmodule
