module TopModule(input clk, input load, input [511:0] data, output reg [511:0] q);
  always @(posedge clk) if(load) q<=data;
  else q<={1'b0,q[510:0]} ^ {q[510:0],1'b0};
endmodule
