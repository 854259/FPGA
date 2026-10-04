module TopModule(input [15:0] a,b,input Cin,output [15:0] y,output Co);
wire c8;
Add8 lo(.a(a[7:0]),.b(b[7:0]),.cin(Cin),.y(y[7:0]),.co(c8));
Add8 hi(.a(a[15:8]),.b(b[15:8]),.cin(c8),.y(y[15:8]),.co(Co));
endmodule

module Add8(input [7:0] a,b,input cin,output [7:0] y,output co);
wire [8:0] c;assign c[0]=cin;
for(genvar i=0;i<8;i=i+1)begin:bit_add
assign y[i]=a[i]^b[i]^c[i];assign c[i+1]=(a[i]&b[i])|(c[i]&(a[i]^b[i]));end
assign co=c[8];
endmodule
