`timescale 1ns/1ps
// Prompt-only probe; R2Probe and R2_PROBE_RESULT retain the reused runner's
// wire protocol. This is a separate R3 semantic validation, not an R2 repair.
module R2Probe;
    reg clk = 0;
    reg reset = 1;
    wire [4:0] q;
    integer state = 1;
    integer checks = 0;
    integer mismatches = 0;
    integer step_no = 0;
    integer i;
    TopModule dut(.clk(clk), .reset(reset), .q(q));

    // Independent whole-state arithmetic oracle, not the DUT bit recurrence.
    function integer next_state(input integer old_state);
        begin
            next_state = old_state / 2;
            if ((old_state % 2) == 1)
                next_state = next_state ^ 20;
        end
    endfunction

    task check_q(input [255:0] phase);
        begin
            checks = checks + 1;
            if (q !== state[4:0]) begin
                mismatches = mismatches + 1;
                if (mismatches <= 12)
                    $display("R3_MISMATCH check=%0d step=%0d phase=%0s reset=%0b expected=%05b actual=%05b q4_diff=%0b",
                             checks, step_no, phase, reset, state[4:0], q,
                             q[4] !== state[4]);
            end
        end
    endtask

    task step(input reg reset_value);
        begin
            // All stimuli change while the clock is low, away from its edge.
            reset = reset_value;
            #2;
            check_q("before_posedge_hold");
            clk = 1;
            #1; // allow the DUT's nonblocking state update to settle
            step_no = step_no + 1;
            if (reset_value)
                state = 1;
            else
                state = next_state(state);
            check_q("after_posedge");
            #1;
            clk = 0;
            #2;
        end
    endtask

    initial begin
        // Do not impose any unrequested power-up value before the reset edge.
        #2;
        clk = 1;
        #1;
        check_q("initial_sync_reset");
        #1;
        clk = 0;
        #2;
        step(1);
        for (i = 0; i < 93; i = i + 1)
            step(0);
        for (i = 0; i < 7; i = i + 1)
            step(0);
        step(1); // assert between edges after a known non-reset state
        step(1);
        for (i = 0; i < 31; i = i + 1)
            step(0);
        $display("R2_PROBE_RESULT task=Prob086_lfsr5 checks=%0d mismatches=%0d", checks, mismatches);
        $finish;
    end
endmodule
