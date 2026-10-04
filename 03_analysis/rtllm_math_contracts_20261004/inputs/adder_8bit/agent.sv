module TopModule (
    input  logic [7:0] a,
    input  logic [7:0] b,
    input  logic       cin,
    output logic [7:0] sum,
    output logic       cout
);

    logic [7:0] carry;

    assign carry[0] = cin;

    for (genvar i = 0; i < 8; i++) begin : gen_adder
        if (i == 7) begin
            assign sum[i] = a[i] ^ b[i] ^ carry[i];
            assign cout   = (a[i] & b[i]) | (a[i] & carry[i]) | (b[i] & carry[i]);
        end else begin
            assign sum[i]   = a[i] ^ b[i] ^ carry[i];
            assign carry[i+1] = (a[i] & b[i]) | (a[i] & carry[i]) | (b[i] & carry[i]);
        end
    end

endmodule
