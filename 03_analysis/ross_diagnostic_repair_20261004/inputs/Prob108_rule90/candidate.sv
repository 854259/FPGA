module TopModule (
    input  clk,
    input  load,
    input  [511:0] data,
    output [511:0] q
);

    reg [511:0] q_reg;

    // Rule 90: next state of cell i is XOR of left neighbor (i-1) and right neighbor (i+1)
    // Boundaries q[-1] and q[512] are 0.
    // For i=0: left is 0, right is q_reg[1] -> next = 0 ^ q_reg[1] = q_reg[1]
    // For i=511: left is q_reg[510], right is 0 -> next = q_reg[510] ^ 0 = q_reg[510]
    // For 0 < i < 511: next = q_reg[i-1] ^ q_reg[i+1]

    wire [511:0] next_q;

    // Generate next state for all cells
    // We can compute this using shifts:
    // left neighbors: {1'b0, q_reg[510:0]}
    // right neighbors: {q_reg[510:0], 1'b0}
    // next_q = left_neighbors ^ right_neighbors

    assign next_q = ({1'b0, q_reg[510:0]}) ^ ({q_reg[510:0], 1'b0});

    always @(posedge clk) begin
        if (load) begin
            q_reg <= data;
        end else begin
            q_reg <= next_q;
        end
    end

    assign q = q_reg;

endmodule
