module TopModule (
    input  [3:0] A,
    input  [3:0] B,
    output       A_greater,
    output       A_equal,
    output       A_less
);

    // Perform subtraction A - B using 4-bit adder with B inverted and carry-in = 1 (2's complement)
    // A - B = A + (~B) + 1
    wire [3:0] B_inv = ~B;
    wire [4:0] sub_result = A + B_inv + 1'b1;

    // sub_result[4] is the carry-out from the 4-bit subtraction
    // If carry-out is 1, it means no borrow occurred (A >= B)
    // If carry-out is 0, it means borrow occurred (A < B)
    wire no_borrow = sub_result[4];

    // Check if result is zero (A == B)
    wire is_zero = &(~sub_result[3:0]); // All bits of lower 4 bits are 0

    // A_less: borrow occurred (carry-out = 0)
    assign A_less = ~no_borrow;

    // A_equal: no borrow and result is zero
    assign A_equal = no_borrow & is_zero;

    // A_greater: no borrow and result is non-zero
    assign A_greater = no_borrow & ~is_zero;

endmodule
