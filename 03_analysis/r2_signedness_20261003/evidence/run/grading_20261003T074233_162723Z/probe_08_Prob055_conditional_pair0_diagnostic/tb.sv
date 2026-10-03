`timescale 1ns/1ps
module R2Probe;
    reg [7:0] a, b, c, d;
    wire [7:0] min;
    reg [7:0] values [0:7];
    integer i, j, k, l;
    integer expected;
    integer checks = 0;
    integer mismatches = 0;
    TopModule dut (.a(a), .b(b), .c(c), .d(d), .min(min));
    initial begin
        values[0] = 8'h00; values[1] = 8'h01;
        values[2] = 8'h02; values[3] = 8'h7e;
        values[4] = 8'h7f; values[5] = 8'h80;
        values[6] = 8'hfe; values[7] = 8'hff;
        // Cartesian boundary set puts the minimum in every position and
        // includes equal operands and both sides of the signed boundary.
        for (i = 0; i < 8; i = i + 1)
        for (j = 0; j < 8; j = j + 1)
        for (k = 0; k < 8; k = k + 1)
        for (l = 0; l < 8; l = l + 1) begin
            a = values[i]; b = values[j]; c = values[k]; d = values[l];
            // 32-bit zero-extended integers avoid any signed 8-bit comparison.
            expected = {24'b0, a};
            if ({24'b0, b} < expected) expected = {24'b0, b};
            if ({24'b0, c} < expected) expected = {24'b0, c};
            if ({24'b0, d} < expected) expected = {24'b0, d};
            #1;
            checks = checks + 1;
            if (min !== expected[7:0]) begin
                mismatches = mismatches + 1;
                if (mismatches <= 8)
                    $display("R2_MISMATCH a=%h b=%h c=%h d=%h got=%h expected=%h", a, b, c, d, min, expected[7:0]);
            end
        end
        $display("R2_PROBE_RESULT task=Prob055_conditional checks=%0d mismatches=%0d", checks, mismatches);
        $finish;
    end
endmodule
