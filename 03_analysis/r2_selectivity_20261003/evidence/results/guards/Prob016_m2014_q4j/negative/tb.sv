`timescale 1ns/1ps
module R2Probe;
  reg [3:0] x, y;
  wire [4:0] sum;
  integer xi, yi, expected;
  integer checks = 0, mismatches = 0;
  TopModule dut(.x(x), .y(y), .sum(sum));
  initial begin
    for (xi = 0; xi < 16; xi = xi + 1)
      for (yi = 0; yi < 16; yi = yi + 1) begin
        x = xi; y = yi; expected = xi + yi;
        #1;
        checks = checks + 1;
        if (sum !== expected[4:0]) begin
          mismatches = mismatches + 1;
          if (mismatches <= 5)
            $display("MISMATCH x=%0d y=%0d sum=%b expected=%0d", xi, yi, sum, expected);
        end
      end
    $display("R2_PROBE_RESULT task=Prob016_m2014_q4j checks=%0d mismatches=%0d", checks, mismatches);
    $finish;
  end
endmodule
