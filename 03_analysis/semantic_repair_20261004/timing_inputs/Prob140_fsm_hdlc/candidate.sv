module TopModule (
    input  clk,
    input  reset,
    input  in,
    output disc,
    output flag,
    output err
);

    // State encoding
    // S0: 0 consecutive 1s (last bit was 0)
    // S1: 1 consecutive 1
    // S2: 2 consecutive 1s
    // S3: 3 consecutive 1s
    // S4: 4 consecutive 1s
    // S5: 5 consecutive 1s
    // S6: 6 consecutive 1s
    // S7: 7 or more consecutive 1s (Error state)
    // S_disc: Transient state to assert disc output for one cycle
    // S_flag: Transient state to assert flag output for one cycle

    typedef enum logic [3:0] {
        S0     = 4'b0000,
        S1     = 4'b0001,
        S2     = 4'b0010,
        S3     = 4'b0011,
        S4     = 4'b0100,
        S5     = 4'b0101,
        S6     = 4'b0110,
        S7     = 4'b0111,
        S_disc = 4'b1000,
        S_flag = 4'b1001
    } state_t;

    state_t current_state, next_state;

    // Next state logic
    always_comb begin
        next_state = current_state;
        case (current_state)
            S0: begin
                if (in) next_state = S1;
                else    next_state = S0;
            end
            S1: begin
                if (in) next_state = S2;
                else    next_state = S0;
            end
            S2: begin
                if (in) next_state = S3;
                else    next_state = S0;
            end
            S3: begin
                if (in) next_state = S4;
                else    next_state = S0;
            end
            S4: begin
                if (in) next_state = S5;
                else    next_state = S0;
            end
            S5: begin
                if (in) next_state = S6;
                else    next_state = S_disc; // 0111110 detected
            end
            S6: begin
                if (in) next_state = S7;     // 01111111... detected (Error)
                else    next_state = S_flag; // 01111110 detected
            end
            S7: begin
                if (in) next_state = S7;     // Still error
                else    next_state = S0;     // Error ended, last bit 0
            end
            S_disc: begin
                // Last bit was 0 (part of 0111110).
                // Behave like S0 for next state transition.
                if (in) next_state = S1;
                else    next_state = S0;
            end
            S_flag: begin
                // Last bit was 0 (part of 01111110).
                // Behave like S0 for next state transition.
                if (in) next_state = S1;
                else    next_state = S0;
            end
            default: next_state = S0;
        endcase
    end

    // State register
    always_ff @(posedge clk) begin
        if (reset) begin
            current_state <= S0;
        end else begin
            current_state <= next_state;
        end
    end

    // Output logic (Moore machine: outputs depend only on current state)
    assign disc = (current_state == S_disc);
    assign flag = (current_state == S_flag);
    assign err  = (current_state == S7);

endmodule
