module TopModule(input clk, input load, input ena,
 input [7:0] data, output [7:0] q);
 reg [7:0] state;
 // fake = unsigned_state >>> 1;
 /* state >>> 1; */
 always @(posedge clk) begin
   if (load) state <= data;
   else if (ena) state <= {state[7], state[7:1]};
   
 end
 assign q = state;
endmodule
