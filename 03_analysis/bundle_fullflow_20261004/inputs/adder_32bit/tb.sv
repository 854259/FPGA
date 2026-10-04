`timescale 1ns/1ps
module R2Probe;
reg [32:1] A,B; wire [32:1] S; wire C32; TopModule dut(.A(A),.B(B),.S(S),.C32(C32));
integer ai,bi,ci,domain,bit_index,iteration; integer checks=0,mismatches=0; reg [31:0] rng=32'hc001d00d;
function [31:0] boundary(input integer index); begin case(index)
0:boundary=32'h0;
1:boundary=32'h1;
2:boundary=32'h2;
3:boundary=32'h3;
4:boundary=32'h7f;
5:boundary=32'h80;
6:boundary=32'hff;
7:boundary=32'h100;
8:boundary=32'h7fff;
9:boundary=32'h8000;
10:boundary=32'hffff;
11:boundary=32'h10000;
12:boundary=32'hffffff;
13:boundary=32'h1000000;
14:boundary=32'h55555555;
15:boundary=32'h7fffffff;
16:boundary=32'h80000000;
17:boundary=32'h80000001;
18:boundary=32'haaaaaaaa;
19:boundary=32'hfe000000;
20:boundary=32'hff000000;
21:boundary=32'hfffe0000;
22:boundary=32'hffff0000;
23:boundary=32'hffffff00;
24:boundary=32'hfffffffe;
25:boundary=32'hffffffff;
default:boundary=0;endcase end endfunction
task step_rng; begin rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);end endtask
task check_now;reg [32:0] expected;begin #1;expected={1'b0,A}+{1'b0,B};checks=checks+1;
if({C32,S}!==expected)begin if(mismatches==0)$display("FIRST_MISMATCH a=%h b=%h observed=%h expected=%h",A,B,{C32,S},expected);mismatches=mismatches+1;end end endtask
initial begin
for(ai=0;ai<26;ai=ai+1)for(bi=0;bi<26;bi=bi+1)begin A=boundary(ai);B=boundary(bi);check_now; end
for(domain=0;domain<2;domain=domain+1)for(ai=0;ai<256;ai=ai+1)for(bi=0;bi<256;bi=bi+1)begin
if(domain==0)begin A=ai;B=bi;end else begin A=ai*32'h1010101;B=bi*32'h1010101;end
check_now; end
for(bit_index=0;bit_index<32;bit_index=bit_index+1)begin
A=(32'h1<<bit_index)-32'h1;B=1;check_now;
A=1;B=(32'h1<<bit_index)-32'h1;check_now; end
for(iteration=0;iteration<4096;iteration=iteration+1)begin step_rng;A=rng;step_rng;B=rng;check_now; end
$display("R2_PROBE_RESULT task=adder_32bit checks=%0d mismatches=%0d",checks,mismatches);
if(checks!=135908)$fatal(1,"CHECK_COUNT_INVALID");$finish;end
initial begin #1000000;$fatal(1,"WATCHDOG_EXPIRED");end
endmodule
