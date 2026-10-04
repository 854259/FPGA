module TopModule(input clk,aresetn,x,output reg z);
 reg [1:0] state;
 always @(posedge clk or negedge aresetn)
  if(!aresetn) state<=0;
  else case(state) 0:state<=x?1:0; 1:state<=x?1:2; 2:state<=x?1:0; default:state<=0; endcase
 always @(posedge clk or negedge aresetn) if(!aresetn) z<=0; else z<=(state==2)&&x;
endmodule
