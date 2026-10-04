module TopModule (
    input clk,
    input load,
    input enable,
    input [1:0] mode,
    input [10:0] data,
    output reg [10:0] q
);
    always @(posedge clk) begin
        if (load)
            q <= data;
        else if (enable) begin
            case (mode)
                2'b00: q <= q;
                2'b01: q <= q >>> 1;
                2'b10: q <= q >>> 5;
                2'b11: q <= q >>> 11;
            endcase
        end
    end
endmodule
