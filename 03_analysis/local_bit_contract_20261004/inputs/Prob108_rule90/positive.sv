module TopModule(input clk, input load, input [511:0] data, output reg [511:0] q);
  genvar k;
  generate for(k=0;k<512;k=k+1) begin:cell_update
    if(k==0) always @(posedge clk) if(load) q[k]<=data[k]; else q[k]<=q[k+1];
    else if(k==511) always @(posedge clk) if(load) q[k]<=data[k]; else q[k]<=q[k-1];
    else always @(posedge clk) if(load) q[k]<=data[k]; else q[k]<=q[k-1]^q[k+1];
  end endgenerate
endmodule
