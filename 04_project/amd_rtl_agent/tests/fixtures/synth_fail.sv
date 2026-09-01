module TopModule(
    output logic y
);
    initial begin
        y = 1'b0;
        forever #1 y = ~y;
    end
endmodule
