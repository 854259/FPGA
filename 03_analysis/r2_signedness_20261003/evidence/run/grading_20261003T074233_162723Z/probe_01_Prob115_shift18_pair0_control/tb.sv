`timescale 1ns/1ps
module R2Probe;
    reg clk = 0;
    reg load = 0;
    reg ena = 0;
    reg [1:0] amount = 0;
    reg [63:0] data = 0;
    wire [63:0] q;
    reg [63:0] expected;
    integer checks = 0;
    integer mismatches = 0;
    integer n;
    TopModule dut (.clk(clk), .load(load), .ena(ena), .amount(amount),
                   .data(data), .q(q));

    // First call loads known data. No assertion about unspecified power-up q.
    // Drive with clk low, then sample 1 ns after the rising edge (after NBA).
    task step;
        input next_load;
        input next_ena;
        input [1:0] next_amount;
        input [63:0] next_data;
        begin
            clk = 0;
            #2;
            load = next_load;
            ena = next_ena;
            amount = next_amount;
            data = next_data;
            if (next_load)
                expected = next_data;
            else if (next_ena) begin
                case (next_amount)
                    2'b00: expected = {expected[62:0], 1'b0};
                    2'b01: expected = {expected[55:0], 8'b0};
                    2'b10: expected = {expected[63], expected[63:1]};
                    2'b11: expected = {{8{expected[63]}}, expected[63:8]};
                endcase
            end
            #2;
            clk = 1;
            #1;
            checks = checks + 1;
            if (q !== expected) begin
                mismatches = mismatches + 1;
                if (mismatches <= 8)
                    $display("R2_MISMATCH n=%0d got=%h expected=%h", checks, q, expected);
            end
            #1;
            clk = 0;
        end
    endtask

    initial begin
        // Negative and nonnegative loads, both right-shift distances.
        step(1, 0, 0, 64'h8123456789abcdef);
        step(0, 1, 2, 0);
        step(0, 1, 3, 0);
        step(1, 0, 0, 64'h7123456789abcdef);
        step(0, 1, 2, 0);
        step(0, 1, 3, 0);
        // Overflow is discarded on left shifts; bit patterns remain 64-bit.
        step(1, 0, 0, 64'h8123456789abcdef);
        step(0, 1, 0, 0);
        step(0, 1, 1, 0);
        // Load wins even when shifting is enabled; disabled holds for all modes.
        for (n = 0; n < 4; n = n + 1) begin
            step(1, 1, n[1:0], 64'hfedcba9876543210 ^ n);
            step(0, 0, n[1:0], 64'h0000000000000000);
        end
        step(1, 0, 0, 64'h8000000000000000);
        for (n = 0; n < 9; n = n + 1)
            step(0, 1, 3, 0);
        step(1, 0, 0, 64'hffffffffffffffff);
        step(0, 1, 2, 0);
        step(1, 0, 0, 64'h0000000000000000);
        step(0, 1, 3, 0);
        $display("R2_PROBE_RESULT task=Prob115_shift18 checks=%0d mismatches=%0d", checks, mismatches);
        $finish;
    end
endmodule
