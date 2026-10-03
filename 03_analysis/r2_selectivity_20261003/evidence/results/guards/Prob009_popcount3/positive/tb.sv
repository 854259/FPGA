`timescale 1ns/1ps
module R2Probe;
  reg [2:0] in;
  wire [1:0] out;
  integer value, bit_index, expected;
  integer checks = 0, mismatches = 0;
  TopModule dut(.in(in), .out(out));
  initial begin
    for (value = 0; value < 8; value = value + 1) begin
      in = value;
      expected = 0;
      for (bit_index = 0; bit_index < 3; bit_index = bit_index + 1)
        expected = expected + ((value >> bit_index) & 1);
      #1;
      checks = checks + 1;
      if (out !== expected[1:0]) begin
        mismatches = mismatches + 1;
        $display("MISMATCH in=%b out=%b expected=%0d", in, out, expected);
      end
    end
    $display("R2_PROBE_RESULT task=Prob009_popcount3 checks=%0d mismatches=%0d", checks, mismatches);
    $finish;
  end
endmodule
