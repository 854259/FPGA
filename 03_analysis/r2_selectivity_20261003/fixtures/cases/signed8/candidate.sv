module TopModule(input clk, input load, input ena,
 input [7:0] data, output [7:0] q);
 reg signed [7:0] state;
 
 always @(posedge clk) begin
   if (load) state <= data;
   else if (ena) state <= state >>> 1;
   
 end
 assign q = state;
endmodule
