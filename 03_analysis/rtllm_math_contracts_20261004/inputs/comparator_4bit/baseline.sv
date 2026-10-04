module TopModule (
    input  wire [3:0] A,
    input  wire [3:0] B,
    output wire       A_greater,
    output wire       A_equal,
    output wire       A_less
);

    // Perform subtraction A - B using a 4-bit subtractor.
    // We use a 5-bit wire to capture the borrow-out from the MSB.
    wire [4:0] diff;
    assign diff = {1'b0, A} - {1'b0, B};

    // diff[4] is the borrow-out.
    // If A < B, borrow-out is 1.
    // If A >= B, borrow-out is 0.
    assign A_less = diff[4];

    // If A == B, the lower 4 bits of the difference are all 0.
    // Note: We must ensure that if A < B, A_equal is 0.
    // Since A_less is 1 when A < B, and A_equal checks for zero result,
    // we need to be careful. However, if A < B, the result of A-B (in 2's complement sense within 4 bits)
    // is not zero unless A==B. But wait, if A < B, the 4-bit result wraps around.
    // For example, 0 - 1 = 1111 (15). This is not 0.
    // So checking if diff[3:0] == 0 is sufficient for equality, provided we handle the borrow correctly.
    // Actually, if A == B, diff[3:0] is 0 and diff[4] is 0.
    // If A != B, diff[3:0] is non-zero OR diff[4] is 1.
    // Let's refine:
    // A_equal is true if and only if A == B.
    // This happens when diff[3:0] is 0 AND diff[4] is 0.
    // However, simply checking diff[3:0] == 0 is enough because if A < B, diff[3:0] is non-zero (unless A=B, which is handled).
    // Wait, is it possible for A < B and diff[3:0] == 0?
    // A - B = 0 mod 16. This implies A = B mod 16. Since A and B are 4-bit, A must equal B.
    // So if diff[3:0] == 0, then A == B.
    // Therefore:
    assign A_equal = (diff[3:0] == 4'b0000);

    // A_greater is true if A > B.
    // This happens if there is no borrow (diff[4] == 0) AND the result is not zero (diff[3:0] != 0).
    assign A_greater = (~diff[4]) & (~A_equal);

endmodule
