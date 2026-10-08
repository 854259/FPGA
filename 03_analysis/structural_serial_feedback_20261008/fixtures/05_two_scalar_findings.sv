module Circuit(input clk, input a, output reg u, output logic v);
always @* begin u=a; v=0; end
always @(posedge clk) begin u<=0; v<=a; end
endmodule
