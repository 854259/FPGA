`timescale 1ns/1ps
module R2Probe;
    reg clk = 0;
    reg load = 0;
    reg enable = 0;
    reg [1:0] mode = 0;
    reg [16:0] data = 0;
    wire [16:0] q;
    reg [16:0] expected;
    reg [16:0] value;
    integer checks = 0;
    integer mismatches = 0;
    integer p, n, j;
    TopModule dut (.clk(clk), .load(load), .enable(enable), .mode(mode), .data(data), .q(q));

    // Oracle implements the bit definition directly, without shift operators or DUT internals.
    function [16:0] sign_fill;
        input [16:0] bits;
        input integer distance;
        integer index;
        begin
            for (index = 0; index < 17; index = index + 1)
                if (index + distance < 17)
                    sign_fill[index] = bits[index + distance];
                else
                    sign_fill[index] = bits[16];
        end
    endfunction

    task check;
        begin
            checks = checks + 1;
            if (q !== expected) begin
                mismatches = mismatches + 1;
                if (mismatches <= 8)
                    $display("BOUNDARY_MISMATCH task=Arithmetic17Boundary check=%0d got=%h expected=%h", checks, q, expected);
            end
        end
    endtask

    task step;
        input next_load;
        input next_enable;
        input [1:0] next_mode;
        input [16:0] next_data;
        integer distance;
        begin
            clk = 0;
            #2;
            load = next_load;
            enable = next_enable;
            mode = next_mode;
            data = next_data;
            #1;
            // Initial state is unspecified; check before-edge holds only after the first load.
            if (checks > 0) check;
            if (next_load)
                expected = next_data;
            else if (next_enable) begin
                case (next_mode)
                    2'b00: distance = 0;
                    2'b01: distance = 1;
                    2'b10: distance = 8;
                    2'b11: distance = 18;
                endcase
                expected = sign_fill(expected, distance);
            end
            #1;
            clk = 1;
            #1;
            check;
            #1;
            clk = 0;
        end
    endtask

    initial begin
        // Both signs, zero, all ones, sign-only, alternating bits and largest nonnegative.
        for (p = 0; p < 6; p = p + 1) begin
            case (p)
                0: value = 17'b00000000000000000;
                1: value = 17'b11111111111111111;
                2: value = 17'b10000000000000000;
                3: value = 17'b01111111111111111;
                4: value = 17'b10101010101010101;
                5: value = 17'b01010101010101010;
            endcase
            for (n = 0; n < 4; n = n + 1) begin
                step(1, 1, n[1:0], value);
                step(0, 0, n[1:0], ~value);
                step(0, 1, n[1:0], ~value);
            end
            for (n = 0; n < 4; n = n + 1)
                step(1, 0, n[1:0], value);
            for (j = 0; j < 20; j = j + 1)
                step(0, 1, 1, ~value);
        end
        // 216 rising-edge observations plus 215 defined before-edge hold observations.
        $display("R2_PROBE_RESULT task=Arithmetic17Boundary checks=%0d mismatches=%0d", checks, mismatches);
        $finish;
    end
endmodule
