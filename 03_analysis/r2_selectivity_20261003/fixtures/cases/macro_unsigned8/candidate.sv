`define W 8
module TopModule(input clk, input load, input ena,
 input [`W-1:0] data, output [`W-1:0] q);
 reg [`W-1:0] state;
 
 always @(posedge clk) begin
   if (load) state <= data;
   else if (ena) state <= state >>> 1;
   
 end
 assign q = state;
endmodule
`undef W
