module TopModule (
    input  clk,
    input  reset,
    input  data,
    output [3:0] count,
    output counting,
    output done,
    input  ack
);

    // State encoding
    // S0: Search for '1'
    // S1: Found '1', search for '1'
    // S2: Found '11', search for '0'
    // S3: Found '110', search for '1' -> Start detected
    // S4: Shift in delay[3] (MSB)
    // S5: Shift in delay[2]
    // S6: Shift in delay[1]
    // S7: Shift in delay[0] (LSB)
    // S8: Counting
    // S9: Done, wait for ack

    typedef enum logic [3:0] {
        S0 = 4'd0,
        S1 = 4'd1,
        S2 = 4'd2,
        S3 = 4'd3,
        S4 = 4'd4,
        S5 = 4'd5,
        S6 = 4'd6,
        S7 = 4'd7,
        S8 = 4'd8,
        S9 = 4'd9
    } state_t;

    state_t state, next_state;

    // Registers
    logic [3:0] delay_reg;
    logic [3:0] count_reg;
    logic [9:0] cycle_cnt; // Counts up to 1000 (0 to 999)
    logic counting_reg;
    logic done_reg;

    // Output assignments
    assign count = (state == S8) ? count_reg : 4'b0;
    assign counting = counting_reg;
    assign done = done_reg;

    // Next state logic and register updates
    always_comb begin
        next_state = state;
        delay_reg = delay_reg;
        count_reg = count_reg;
        cycle_cnt = cycle_cnt;
        counting_reg = counting_reg;
        done_reg = done_reg;

        case (state)
            S0: begin
                if (data == 1'b1)
                    next_state = S1;
                else
                    next_state = S0;
            end
            S1: begin
                if (data == 1'b1)
                    next_state = S2;
                else
                    next_state = S0;
            end
            S2: begin
                if (data == 1'b0)
                    next_state = S3;
                else
                    next_state = S2;
            end
            S3: begin
                if (data == 1'b1)
                    next_state = S4;
                else
                    next_state = S0;
            end
            S4: begin
                // Shift in MSB of delay
                delay_reg = {delay_reg[2:0], data};
                next_state = S5;
            end
            S5: begin
                delay_reg = {delay_reg[2:0], data};
                next_state = S6;
            end
            S6: begin
                delay_reg = {delay_reg[2:0], data};
                next_state = S7;
            end
            S7: begin
                delay_reg = {delay_reg[2:0], data};
                next_state = S8;
                count_reg = delay_reg;
                cycle_cnt = 10'd0;
                counting_reg = 1'b1;
                done_reg = 1'b0;
            end
            S8: begin
                counting_reg = 1'b1;
                if (cycle_cnt == 10'd999) begin
                    // End of 1000 cycles
                    if (count_reg == 4'd0) begin
                        // Counting finished
                        next_state = S9;
                        counting_reg = 1'b0;
                        done_reg = 1'b1;
                    end else begin
                        // Decrement count and reset cycle counter
                        count_reg = count_reg - 1;
                        cycle_cnt = 10'd0;
                    end
                end else begin
                    cycle_cnt = cycle_cnt + 1;
                end
            end
            S9: begin
                done_reg = 1'b1;
                if (ack == 1'b1) begin
                    next_state = S0;
                    done_reg = 1'b0;
                    counting_reg = 1'b0;
                end
            end
            default: next_state = S0;
        endcase
    end

    // Sequential logic
    always_ff @(posedge clk) begin
        if (reset) begin
            state <= S0;
            delay_reg <= 4'b0;
            count_reg <= 4'b0;
            cycle_cnt <= 10'd0;
            counting_reg <= 1'b0;
            done_reg <= 1'b0;
        end else begin
            state <= next_state;
            delay_reg <= delay_reg;
            count_reg <= count_reg;
            cycle_cnt <= cycle_cnt;
            counting_reg <= counting_reg;
            done_reg <= done_reg;
        end
    end

endmodule
