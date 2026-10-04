`timescale 1ns/1ps
module R2Probe;
reg [15:0] a,b; reg Cin; wire [15:0] y; wire Co; TopModule dut(.a(a),.b(b),.Cin(Cin),.y(y),.Co(Co));
integer ai,bi,ci,domain,bit_index,iteration; integer checks=0,mismatches=0; reg [31:0] rng=32'h1badb002;
function [15:0] boundary(input integer index); begin case(index)
0:boundary=16'h0;
1:boundary=16'h1;
2:boundary=16'h2;
3:boundary=16'h3;
4:boundary=16'h7f;
5:boundary=16'h80;
6:boundary=16'hff;
7:boundary=16'h100;
8:boundary=16'h5555;
9:boundary=16'h7fff;
10:boundary=16'h8000;
11:boundary=16'h8001;
12:boundary=16'haaaa;
13:boundary=16'hfe00;
14:boundary=16'hff00;
15:boundary=16'hfffe;
16:boundary=16'hffff;
default:boundary=0;endcase end endfunction
task step_rng; begin rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);end endtask
task check_now;reg [16:0] expected;begin #1;expected={1'b0,a}+{1'b0,b}+Cin;checks=checks+1;
if({Co,y}!==expected)begin if(mismatches==0)$display("FIRST_MISMATCH a=%h b=%h observed=%h expected=%h",a,b,{Co,y},expected);mismatches=mismatches+1;end end endtask
initial begin
for(ai=0;ai<17;ai=ai+1)for(bi=0;bi<17;bi=bi+1)begin a=boundary(ai);b=boundary(bi);for(ci=0;ci<2;ci=ci+1)begin Cin=ci;check_now;end end
for(domain=0;domain<2;domain=domain+1)for(ai=0;ai<256;ai=ai+1)for(bi=0;bi<256;bi=bi+1)begin
if(domain==0)begin a=ai;b=bi;end else begin a=ai*16'h101;b=bi*16'h101;end
for(ci=0;ci<2;ci=ci+1)begin Cin=ci;check_now;end end
for(bit_index=0;bit_index<16;bit_index=bit_index+1)begin
a=(16'h1<<bit_index)-16'h1;b=1;for(ci=0;ci<2;ci=ci+1)begin Cin=ci;check_now;end
a=1;b=(16'h1<<bit_index)-16'h1;for(ci=0;ci<2;ci=ci+1)begin Cin=ci;check_now;end end
for(iteration=0;iteration<4096;iteration=iteration+1)begin step_rng;a=rng;step_rng;b=rng;for(ci=0;ci<2;ci=ci+1)begin Cin=ci;check_now;end end
$display("R2_PROBE_RESULT task=adder_16bit checks=%0d mismatches=%0d",checks,mismatches);
if(checks!=270978)$fatal(1,"CHECK_COUNT_INVALID");$finish;end
initial begin #1000000;$fatal(1,"WATCHDOG_EXPIRED");end
endmodule
