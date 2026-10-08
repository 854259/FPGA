module Circuit(input clk, input a, output reg q);
parameter CHOICE=1;
if(CHOICE) begin always @(posedge clk) q<=a; end else begin always @(posedge clk) q<=0; end
endmodule
