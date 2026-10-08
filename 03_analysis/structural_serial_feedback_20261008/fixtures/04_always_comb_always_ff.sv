module Circuit(input clk, input reset, input a, output logic completion);
always_comb begin completion=a; end
always_ff @(posedge clk or posedge reset) begin if(reset) completion<=0; else completion<=a; end
endmodule
