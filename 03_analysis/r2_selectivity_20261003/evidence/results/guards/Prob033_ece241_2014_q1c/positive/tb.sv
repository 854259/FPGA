`timescale 1ns/1ps
module R2Probe;
  reg [7:0] a, b;
  wire [7:0] s;
  wire overflow;
  integer ai, bi, sa, sb, total, expected_s, expected_overflow;
  integer checks = 0, mismatches = 0;
  TopModule dut(.a(a), .b(b), .s(s), .overflow(overflow));
  initial begin
    for (ai = 0; ai < 256; ai = ai + 1)
      for (bi = 0; bi < 256; bi = bi + 1) begin
        a = ai; b = bi;
        // Independent integer oracle: decode two's complement mathematically.
        sa = (ai < 128) ? ai : ai - 256;
        sb = (bi < 128) ? bi : bi - 256;
        total = sa + sb;
        expected_s = (total + 512) % 256;
        expected_overflow = (total < -128 || total > 127);
        #1;
        checks = checks + 1;
        if (s !== expected_s[7:0] || overflow !== expected_overflow[0]) begin
          mismatches = mismatches + 1;
          if (mismatches <= 5)
            $display("MISMATCH a=%0d b=%0d s=%h ov=%b expected_s=%0d expected_ov=%0d",
                     ai, bi, s, overflow, expected_s, expected_overflow);
        end
      end
    $display("R2_PROBE_RESULT task=Prob033_ece241_2014_q1c checks=%0d mismatches=%0d", checks, mismatches);
    $finish;
  end
endmodule
