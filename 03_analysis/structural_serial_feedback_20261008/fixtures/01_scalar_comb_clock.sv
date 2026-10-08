module Circuit(input clk, input a, output logic flag);
always @(*) flag = a;
always @(posedge clk) flag <= a;
endmodule
