module TopModule(input [32:1] A,B,output [32:1] S,output C32);
wire c16;
CLA16 lo(.a(A[16:1]),.b(B[16:1]),.cin(1'b0),.s(S[16:1]),.cout(c16));
CLA16 hi(.a(A[32:17]),.b(B[32:17]),.cin(c16),.s(S[32:17]),.cout(C32));
endmodule

module CLA16(input [15:0] a,b,input cin,output [15:0] s,output cout);
wire [15:0] p,g,c;wire [3:0] P,G;wire [4:0] gc;
assign p=a^b;assign g=a&b;assign gc[0]=cin;
for(genvar block_i=0;block_i<4;block_i=block_i+1)begin:groups
localparam K=block_i*4;
assign P[block_i]=&p[K+:4];
assign G[block_i]=g[K+3]|(p[K+3]&g[K+2])|(p[K+3]&p[K+2]&g[K+1])|(p[K+3]&p[K+2]&p[K+1]&g[K]);
assign c[K]=gc[block_i];
assign c[K+1]=g[K]|(p[K]&gc[block_i]);
assign c[K+2]=g[K+1]|(p[K+1]&g[K])|(p[K+1]&p[K]&gc[block_i]);
assign c[K+3]=g[K+2]|(p[K+2]&g[K+1])|(p[K+2]&p[K+1]&g[K])|(p[K+2]&p[K+1]&p[K]&gc[block_i]);
end
assign gc[1]=(G[0])|(P[0]&cin);
assign gc[2]=(G[1])|(P[1]&G[0])|(P[1]&P[0]&cin);
assign gc[3]=(G[2])|(P[2]&G[1])|(P[2]&P[1]&G[0])|(P[2]&P[1]&P[0]&cin);
assign gc[4]=(G[3])|(P[3]&G[2])|(P[3]&P[2]&G[1])|(P[3]&P[2]&P[1]&G[0])|(P[3]&P[2]&P[1]&P[0]&cin);
assign s=p^c;assign cout=gc[4];
endmodule
