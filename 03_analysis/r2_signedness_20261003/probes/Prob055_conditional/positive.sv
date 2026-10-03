// Hand-written priority selection, independent of the candidate's tournament.
module TopModule (input [7:0] a, b, c, d, output [7:0] min);
    assign min = (a <= b && a <= c && a <= d) ? a :
                 (b <= c && b <= d) ? b :
                 (c <= d) ? c : d;
endmodule
