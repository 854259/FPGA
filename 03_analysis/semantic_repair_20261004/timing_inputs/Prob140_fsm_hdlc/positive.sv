module TopModule(input clk,reset,in,output reg disc,flag,err);
 reg [2:0] count;
 always @(posedge clk) begin
  if(reset) begin count<=0;disc<=0;flag<=0;err<=0; end
  else begin
   disc<=count==5&&!in; flag<=count==6&&!in; err<=in&&(count>=6);
   if(!in) count<=0; else if(count<7) count<=count+1'b1;
  end
 end
endmodule
