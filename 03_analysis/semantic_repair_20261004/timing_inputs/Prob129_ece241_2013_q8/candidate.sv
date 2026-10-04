module TopModule (
    input  clk,
    input  aresetn,
    input  x,
    output z
);

    // State encoding for 3 states
    // S0: Initial state / No match
    // S1: Matched '1'
    // S2: Matched '10'
    localparam S0 = 2'b00;
    localparam S1 = 2'b01;
    localparam S2 = 2'b10;

    reg [1:0] state_reg;
    reg [1:0] state_next;

    // Asynchronous reset on negative edge of aresetn? 
    // The prompt says "negative edge triggered asynchronous reset".
    // Usually, aresetn is active low. "Negative edge triggered" for an async reset 
    // typically means the reset happens when aresetn goes from 1 to 0.
    // However, standard async reset logic is level-sensitive. 
    // Let's re-read carefully: "negative edge triggered asynchronous reset".
    // This is a bit ambiguous. It could mean:
    // 1. The reset is asynchronous and active on the falling edge of aresetn.
    // 2. The reset is asynchronous and active low (level sensitive).
    // Given "aresetn" naming convention, it's almost certainly active low.
    // "Negative edge triggered" might be a slight misnomer for "active low async reset" 
    // or it implies we should detect the falling edge. 
    // But standard FPGA practice for "aresetn" is level-sensitive async reset.
    // If it strictly means edge-triggered, we'd need a flip-flop to detect the edge.
    // However, most "Mealy machine" problems with "aresetn" imply level-sensitive async reset.
    // Let's look at the wording again: "negative edge triggered asynchronous reset".
    // If I implement a level-sensitive reset, it's standard.
    // If I implement an edge-triggered reset, I need to detect the falling edge of aresetn.
    // Let's assume standard active-low asynchronous reset (level sensitive) because 
    // "edge triggered" usually applies to the clock. If the reset itself is edge triggered,
    // it's rarely called "asynchronous" in the same breath without clarification, 
    // because async usually implies level sensitivity. 
    // BUT, if it explicitly says "negative edge triggered", I should probably respect that.
    // However, detecting an async edge requires a sync chain or a specific edge detector.
    // Let's stick to the most common interpretation in digital design courses:
    // "Asynchronous reset" = level sensitive. "Negative edge triggered" might refer to the clock?
    // No, "Assume all sequential logic is triggered on the positive edge of the clock."
    // So the clock is pos-edge. The reset is "negative edge triggered asynchronous".
    // This is contradictory. Async resets are level sensitive. Edge-triggered resets are synchronous 
    // (or require a specific edge-detect circuit).
    // Let's assume it means **Active Low Asynchronous Reset** (level sensitive). 
    // Why? Because "aresetn" is the standard name for active-low async reset.
    // If it were edge triggered, it would likely be named differently or described as a pulse.
    // I will implement a standard active-low asynchronous reset.

    // State Register
    always @(posedge clk or negedge aresetn) begin
        if (!aresetn) begin
            state_reg <= S0;
        end else begin
            state_reg <= state_next;
        end
    end

    // Next State Logic (Combinational)
    always @(*) begin
        // Default assignment
        state_next = S0;
        
        case (state_reg)
            S0: begin
                if (x) begin
                    state_next = S1;
                end else begin
                    state_next = S0;
                end
            end
            S1: begin
                if (x) begin
                    // Stay in S1 (matched '1', new '1' is start of new sequence)
                    state_next = S1;
                end else begin
                    // Matched '10'
                    state_next = S2;
                end
            end
            S2: begin
                if (x) begin
                    // Matched '101' -> Go to S1 (overlapping: the '1' at end is start of new)
                    state_next = S1;
                end else begin
                    // Matched '100' -> Go to S0
                    state_next = S0;
                end
            end
            default: begin
                state_next = S0;
            end
        endcase
    end

    // Output Logic (Mealy: depends on state and input)
    // z is asserted when sequence "101" is detected.
    // This happens when we are in S2 and input x is 1.
    assign z = (state_reg == S2) && x;

endmodule
