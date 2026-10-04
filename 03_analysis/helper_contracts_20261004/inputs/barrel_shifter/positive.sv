module TopModule(input [7:0] in,input [2:0] ctrl,output [7:0] out);
wire [7:0] s4,s2;
mux2X1 #(.WIDTH(8)) m4(.d0(in),.d1({4'b0,in[7:4]}),.sel(ctrl[2]),.y(s4));
mux2X1 #(.WIDTH(8)) m2(.d0(s4),.d1({2'b0,s4[7:2]}),.sel(ctrl[1]),.y(s2));
mux2X1 #(.WIDTH(8)) m1(.d0(s2),.d1({1'b0,s2[7:1]}),.sel(ctrl[0]),.y(out));
endmodule

module mux2X1 #(parameter WIDTH=8)(input [WIDTH-1:0] d0,d1,input sel,output [WIDTH-1:0] y);
assign y=sel?d1:d0;
endmodule
