`timescale 1ns/1ps
module R2Probe;
reg [2:0] A,B; wire A_greater,A_equal,A_less;
TopModule dut(.A(A),.B(B),.A_greater(A_greater),.A_equal(A_equal),.A_less(A_less));
integer a_index,b_index;reg [2:0] expected;
integer checks=0,mismatches=0;
task check_result(input [31:0] observed,input [31:0] expected_value);
begin checks=checks+1;if(observed!==expected_value)begin
if(mismatches==0)$display("FIRST_MISMATCH observed=%h expected=%h",observed,expected_value);
mismatches=mismatches+1;end end endtask
initial begin for(a_index=0;a_index<8;a_index=a_index+1) for(b_index=0;b_index<8;b_index=b_index+1) begin
A=a_index;B=b_index;#1;expected={(a_index>b_index),(a_index==b_index),(a_index<b_index)};check_result({A_greater,A_equal,A_less},expected);end
$display("R2_PROBE_RESULT task=comparator_3bit checks=%0d mismatches=%0d",checks,mismatches);
if(checks!=64)$fatal(1,"CHECK_COUNT_INVALID");$finish;end
initial begin #1000000;$fatal(1,"WATCHDOG_EXPIRED");end
endmodule
