`timescale 1ns/1ps
module R2Probe;
  reg x=0,y=0; wire z; reg expected;
  integer value, repetition, checks=0, mismatches=0;
  TopModule dut(.x(x),.y(y),.z(z));
  initial begin
    // Four distinct input rows are explicit in the public waveform.
    for(repetition=0;repetition<16;repetition=repetition+1) begin
      for(value=0;value<4;value=value+1) begin
        {x,y}=value;
        case(value) 0:expected=1; 1:expected=0; 2:expected=0; 3:expected=1; endcase
        #1; checks=checks+1;
        if(z !== expected) begin
          if(mismatches==0) $display("FIRST_MISMATCH time_ps=%0t x=%b y=%b expected_z=%b observed_z=%b",$time,x,y,expected,z);
          mismatches=mismatches+1;
        end
      end
    end
    $display("R2_PROBE_RESULT task=Prob083_mt2015_q4b checks=%0d mismatches=%0d",checks,mismatches);
    $finish;
  end
  initial begin #99999; $fatal(1,"WATCHDOG: self-check did not complete"); end
endmodule
