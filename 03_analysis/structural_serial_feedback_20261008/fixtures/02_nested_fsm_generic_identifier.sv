module Circuit(input clk, input reset, input a, output wire ready);
localparam IDLE=2'b00, NEXT=2'b01;
reg [1:0] state, next_state;
reg completion_latch;
always @(*) begin
  next_state=state;
  completion_latch=1'b0;
  case(state)
    IDLE: if(a) next_state=NEXT;
    NEXT: begin next_state=IDLE; completion_latch=1'b1; end
    default: next_state=IDLE;
  endcase
end
always @(posedge clk) begin
  if(reset) begin state<=IDLE; completion_latch<=1'b0; end
  else begin state<=next_state; completion_latch<=(state==NEXT)?1'b1:1'b0; end
end
assign ready=completion_latch;
endmodule
