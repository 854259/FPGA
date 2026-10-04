module TopModule(input [3:0] A,B, output A_greater,A_equal,A_less);
wire [4:0] difference={1'b0,A}-{1'b0,B};
assign A_less=difference[4]; assign A_equal=(A==B); assign A_greater=!A_less&&!A_equal;
endmodule
