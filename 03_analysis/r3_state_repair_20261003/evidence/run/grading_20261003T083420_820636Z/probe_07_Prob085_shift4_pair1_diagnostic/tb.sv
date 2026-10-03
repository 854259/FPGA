`timescale 1ns/1ps
module R2Probe;
  reg clk = 0, areset = 0, load = 0, ena = 0;
  reg [3:0] data = 0;
  wire [3:0] q;
  integer value, step, expected;
  integer checks = 0, mismatches = 0;
  TopModule dut(.clk(clk), .areset(areset), .load(load), .ena(ena), .data(data), .q(q));
  task check;
    input integer wanted;
    begin
      checks = checks + 1;
      if (q !== wanted[3:0]) begin
        mismatches = mismatches + 1;
        if (mismatches <= 5)
          $display("MISMATCH check=%0d q=%b expected=%0d", checks, q, wanted);
      end
    end
  endtask
  task tick;
    input ld, en;
    input [3:0] datum;
    begin
      // Inputs are driven while the clock is low; check only after NBA updates.
      load = ld; ena = en; data = datum;
      #2; clk = 1; #1; clk = 0; #1;
    end
  endtask
  initial begin
    // Establish state by the specified asynchronous reset, without an active edge.
    #2; areset = 1; #1; check(0); #1; areset = 0; #1;
    for (value = 0; value < 16; value = value + 1) begin
      tick(1, 0, value); check(value);
      tick(0, 0, 0); check(value);                  // hold
      tick(1, 1, value); check(value);              // load wins over enable
      expected = value;
      for (step = 0; step < 5; step = step + 1) begin
        expected = expected / 2;                   // unsigned integer oracle
        tick(0, 1, 0); check(expected);
      end
      tick(1, 0, value); check(value);
      load = 1; ena = 1; data = 15;
      #2; areset = 1; #1; check(0);                 // reset away from clock edge
      tick(1, 1, 15); check(0);                    // reset wins over load/enable
      #1; areset = 0; #1; check(0);                // release causes no load
      tick(1, 0, value); check(value);
    end
    $display("R2_PROBE_RESULT task=Prob085_shift4 checks=%0d mismatches=%0d", checks, mismatches);
    $finish;
  end
endmodule
