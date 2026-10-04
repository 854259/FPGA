module TopModule(input [7:0] a,b,input cin,output [7:0] sum,output cout);
wire [8:0] carry;assign carry[0]=cin;genvar i;generate for(i=0;i<8;i=i+1)begin assign sum[i]=a[i]^b[i]^carry[i];assign carry[i+1]=(a[i]&b[i])|(a[i]&carry[i])|(b[i]&carry[i]);end endgenerate assign cout=carry[8];endmodule
