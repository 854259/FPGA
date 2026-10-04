module TopModule (
    input  logic [7:0] A,
    input  logic [7:0] B,
    output logic [15:0] product
);

    logic [15:0] partial_product;
    logic [15:0] shifted_A;
    integer i;

    always_comb begin
        partial_product = 16'b0;
        shifted_A = {8'b0, A};

        for (i = 0; i < 8; i = i + 1) begin
            if (B[i]) begin
                partial_product = partial_product + shifted_A;
            end
            shifted_A = shifted_A << 1;
        end

        product = partial_product;
    end

endmodule
