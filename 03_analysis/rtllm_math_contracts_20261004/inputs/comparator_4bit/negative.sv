module TopModule(input [3:0] A,B, output A_greater,A_equal,A_less);
assign A_greater=(A[2:0]>B[2:0]); assign A_equal=(A[2:0]==B[2:0]); assign A_less=(A[2:0]<B[2:0]);
endmodule
