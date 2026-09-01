module tb;
    logic a;
    logic b;
    wire dut_y;
    wire ref_y;
    integer mismatches;
    integer i;

    TopModule dut(.a(a), .b(b), .y(dut_y));
    RefModule reference(.a(a), .b(b), .y(ref_y));

    initial begin
        mismatches = 0;
        for (i = 0; i < 4; i = i + 1) begin
            {a, b} = i[1:0];
            #1;
            if (dut_y !== ref_y)
                mismatches = mismatches + 1;
        end
        $display("Mismatches: %0d", mismatches);
        $finish;
    end
endmodule
