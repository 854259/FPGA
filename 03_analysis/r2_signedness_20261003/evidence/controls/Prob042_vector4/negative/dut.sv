// Deliberate semantic error: zero extension loses the signed value.
module TopModule (input [7:0] in, output [31:0] out);
    assign out = {24'b0, in};
endmodule
