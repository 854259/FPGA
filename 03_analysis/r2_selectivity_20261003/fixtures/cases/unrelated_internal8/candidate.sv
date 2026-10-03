module TopModule(input clk, input load, input ena,
 input [7:0] data, output [7:0] q);
 reg [7:0] state;
 reg [7:0] helper;
 always @(posedge clk) begin
   if (load) state <= data;
   else if (ena) state <= $signed(state) >>> 1;
   helper <= helper >>> 1;
 end
 assign q = state;
endmodule
