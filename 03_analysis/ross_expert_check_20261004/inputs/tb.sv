`timescale 1ns/1ps
module tb;
reg [7:0] a,b,expected; wire [7:0] sum; integer checks=0;
TopModule dut(.a(a),.b(b),.sum(sum));
task check(input [7:0] x,y);
begin a=x; b=y; expected=x+y; #1;
if (sum !== expected) begin $display("TEST_FAIL time=%0t a=%0d b=%0d expected=%0d observed=%0d",$time,a,b,expected,sum); $fatal(1,"comparison failed"); end
checks=checks+1; end
endtask
initial begin
check(1,1); check(0,0); check(254,1); check(255,1); check(128,128);
$display("TEST_PASS checks=%0d",checks); $finish;
end
initial begin #15; $fatal(1,"watchdog expired"); end
endmodule
