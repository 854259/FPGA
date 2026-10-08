module Circuit(input clk, input a, output reg q);
always @* begin : local_scope q=a; end
always @(posedge clk) q<=a;
endmodule
