module TopModule (
    input  wire [7:0] A,
    input  wire [7:0] B,
    output wire [15:0] product
);

    // Internal signal for the product calculation
    wire [15:0] product_int;

    // Generate the product using shift-and-add logic
    // For each bit i of B, if B[i] is 1, add (A << i) to the result
    assign product_int = 
        (B[0] ? (A << 0) : 16'd0) +
        (B[1] ? (A << 1) : 16'd0) +
        (B[2] ? (A << 2) : 16'd0) +
        (B[3] ? (A << 3) : 16'd0) +
        (B[4] ? (A << 4) : 16'd0) +
        (B[5] ? (A << 5) : 16'd0) +
        (B[6] ? (A << 6) : 16'd0) +
        (B[7] ? (A << 7) : 16'd0);

    // Assign internal product to output
    assign product = product_int;

endmodule
