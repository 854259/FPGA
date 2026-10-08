// Synthetic mutant: a late stop incorrectly completes an already-invalid frame.
module TopModule(input clock, input rst, input rx, output reg received, output reg [2:0] payload);
  integer phase;
  reg [2:0] bits;
  always @(posedge clock) begin
    if (rst) begin phase<=0; received<=0; payload<=0; bits<=0; end
    else begin
      received<=0;
      case (phase)
        0: if (!rx) phase<=1;
        1: begin bits[0]<=rx; phase<=2; end
        2: begin bits[1]<=rx; phase<=3; end
        3: begin bits[2]<=rx; phase<=4; end
        4: if (rx) begin received<=1; payload<=bits; phase<=0; end
        default: phase<=0;
      endcase
    end
  end
endmodule
