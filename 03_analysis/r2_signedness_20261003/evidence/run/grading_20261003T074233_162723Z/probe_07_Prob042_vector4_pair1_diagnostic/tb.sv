`timescale 1ns/1ps
module R2Probe;
    reg [7:0] in;
    wire [31:0] out;
    reg [31:0] expected;
    integer n;
    integer checks = 0;
    integer mismatches = 0;
    TopModule dut (.in(in), .out(out));
    initial begin
        // Independent arithmetic oracle: interpret 8-bit two's complement.
        for (n = 0; n < 256; n = n + 1) begin
            in = n;
            if (n < 128) expected = n;
            else expected = n - 256;
            #1;
            checks = checks + 1;
            if (out !== expected) begin
                mismatches = mismatches + 1;
                if (mismatches <= 8)
                    $display("R2_MISMATCH in=%h got=%h expected=%h", in, out, expected);
            end
        end
        $display("R2_PROBE_RESULT task=Prob042_vector4 checks=%0d mismatches=%0d", checks, mismatches);
        $finish;
    end
endmodule
