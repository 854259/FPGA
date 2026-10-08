module Circuit(input a, output reg q);
always @(*) q=a;
always_comb q=0;
endmodule
