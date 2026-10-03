`timescale 1ns/1ps
module R2Probe;
  reg do_sub;
  reg [7:0] a, b;
  wire [7:0] out;
  wire result_is_zero;
  integer operation, ai, bi, expected, expected_zero;
  integer checks = 0, mismatches = 0;
  TopModule dut(.do_sub(do_sub), .a(a), .b(b), .out(out), .result_is_zero(result_is_zero));
  initial begin
    for (operation = 0; operation < 2; operation = operation + 1)
      for (ai = 0; ai < 256; ai = ai + 1)
        for (bi = 0; bi < 256; bi = bi + 1) begin
          do_sub = operation; a = ai; b = bi;
          // Mathematical modulo, then compare the actual specified 8-bit result.
          expected = operation ? (ai - bi + 256) % 256 : (ai + bi) % 256;
          expected_zero = (expected == 0);
          #1;
          checks = checks + 1;
          if (out !== expected[7:0] || result_is_zero !== expected_zero[0]) begin
            mismatches = mismatches + 1;
            if (mismatches <= 5)
              $display("MISMATCH sub=%0d a=%0d b=%0d out=%h zero=%b expected=%0d expected_zero=%0d",
                       operation, ai, bi, out, result_is_zero, expected, expected_zero);
          end
        end
    $display("R2_PROBE_RESULT task=Prob123_bugs_addsubz checks=%0d mismatches=%0d", checks, mismatches);
    $finish;
  end
endmodule
