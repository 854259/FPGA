module TopModule(input tick, input put, input move,
 input [12:0] word_in, output [12:0] word_out);
 reg [12:0] storage;
 
 always @(posedge tick) begin
   if (put) storage <= word_in;
   else if (move) storage <= {storage[12],storage[12:1]};
   
 end
 assign word_out = storage;
endmodule
