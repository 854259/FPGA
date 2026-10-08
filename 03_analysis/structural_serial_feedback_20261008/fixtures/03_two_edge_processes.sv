module Circuit(input c1, input c2, input a, output reg q);
always @(posedge c1) q <= a;
always @(negedge c2) q <= 0;
endmodule
