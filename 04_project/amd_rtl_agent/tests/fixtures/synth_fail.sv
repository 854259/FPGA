module TopModule(
    input logic a,
    input logic b,
    output logic y
);
    // Legal simulation syntax, but no unique clock or asynchronous reset.
    always @(posedge a or posedge b)
        y <= a ^ b;
endmodule
