module TopModule(
    input clk,
    input reset,
    output [4:0] q
);

    reg [4:0] q_reg;

    // Galois LFSR with taps at positions 5 (index 4) and 3 (index 2)
    // Shift right: q[i] next = q[i+1] for non-tap positions
    // For tap positions: q[i] next = q[i+1] ^ q[0]
    // q[0] is the LSB output bit

    always @(posedge clk) begin
        if (reset) begin
            q_reg <= 5'b00001; // Reset to 1 (binary 00001)
        end else begin
            // Calculate next state
            // q[4] (tap at pos 5): q[4] ^ q[0]
            // q[3] (no tap): q[4]
            // q[2] (tap at pos 3): q[3] ^ q[0]
            // q[1] (no tap): q[2]
            // q[0] (LSB): q[1]
            
            q_reg[4] <= q_reg[4] ^ q_reg[0];
            q_reg[3] <= q_reg[4];
            q_reg[2] <= q_reg[3] ^ q_reg[0];
            q_reg[1] <= q_reg[2];
            q_reg[0] <= q_reg[1];
        end
    end

    assign q = q_reg;

endmodule
