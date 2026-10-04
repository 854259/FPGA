`timescale 1ns/1ps
module R2Probe;
  reg clk=0,load=0; reg [511:0] data=0; wire [511:0] q;
  reg [511:0] model=0,prior,next_model,seed;
  reg left_bit,right_bit; reg [31:0] rng=32'hbe714293;
  integer checks=0,mismatches=0,k,j,n,i;
  TopModule dut(.clk(clk),.load(load),.data(data),.q(q));
  task step(input do_load,input [511:0] value);
    begin
      load=do_load;data=value;prior=model;
      if(do_load) next_model=value;
      else for(j=0;j<512;j=j+1) begin
        left_bit=(j==0)?1'b0:model[j-1];
        right_bit=(j==511)?1'b0:model[j+1];
        next_model[j]=left_bit^right_bit;
      end
      #1;clk=1;#1;model=next_model;
      for(j=0;j<512;j=j+1) begin
        checks=checks+1;
        if(q[j] !== model[j]) begin
          if(mismatches==0) $display("FIRST_MISMATCH time_ps=%0t load=%b data=%h previous_q=%h bit=%0d expected_q_bit=%b observed_q_bit=%b",$time,load,data,prior,j,model[j],q[j]);
          mismatches=mismatches+1;
        end
      end
      clk=0;#1;
    end
  endtask
  initial begin
    // Establish state via the specified load, never constrain unspecified startup.
    for(k=0;k<512;k=k+1) begin
      seed=0;seed[k]=1;step(1,seed);
      for(n=0;n<3;n=n+1) step(0,0);
    end
    for(i=0;i<8;i=i+1) begin
      seed=0;
      for(k=0;k<512;k=k+1) begin
        rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};seed[k]=rng[0];
      end
      case(i) 0:seed=0;1:seed={512{1'b1}};2:seed={256{2'b01}};3:seed={256{2'b10}};endcase
      step(1,seed);for(n=0;n<8;n=n+1) step(0,0);
    end
    $display("R2_PROBE_RESULT task=Prob108_rule90 checks=%0d mismatches=%0d",checks,mismatches);
    $finish;
  end
  initial begin #99999; $fatal(1,"WATCHDOG: self-check did not complete");end
endmodule
