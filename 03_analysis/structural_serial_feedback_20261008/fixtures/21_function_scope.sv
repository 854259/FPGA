module Circuit(input clk, input a, output reg q);
function bit f(input bit x); reg q; begin q=x; f=q; end endfunction
always @(posedge clk) q<=a;
endmodule
