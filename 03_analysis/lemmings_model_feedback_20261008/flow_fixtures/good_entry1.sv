// ARTIFICIAL QUALIFICATION FIXTURE ONLY. Independently hand-authored six-state
// plus dead encoding and entry1 count. No checker state function is reused.
module TopModule(input clk, areset, bump_left, bump_right, ground, dig,
                 output walk_left, walk_right, aaah, digging);
  localparam L=0,R=1,FL=2,FR=3,DL=4,DR=5,SPLAT=6;
  reg [2:0] s;
  integer interval_number;
  always @(posedge clk or posedge areset) begin
    if (areset) begin s<=L; interval_number<=0; end
    else case (s)
      L: begin
        if (!ground) begin s<=FL; interval_number<=1; end
        else if (dig) s<=DL;
        else if (bump_left) s<=R;
      end
      R: begin
        if (!ground) begin s<=FR; interval_number<=1; end
        else if (dig) s<=DR;
        else if (bump_right) s<=L;
      end
      DL: if (!ground) begin s<=FL; interval_number<=1; end
      DR: if (!ground) begin s<=FR; interval_number<=1; end
      FL: begin
        if (ground) begin
          if (interval_number>20) s<=SPLAT; else s<=L;
          interval_number<=0;
        end else if (interval_number<21) interval_number<=interval_number+1;
      end
      FR: begin
        if (ground) begin
          if (interval_number>20) s<=SPLAT; else s<=R;
          interval_number<=0;
        end else if (interval_number<21) interval_number<=interval_number+1;
      end
      SPLAT: s<=SPLAT;
      default: s<=L;
    endcase
  end
  assign walk_left=s==L;
  assign walk_right=s==R;
  assign aaah=(s==FL)||(s==FR);
  assign digging=(s==DL)||(s==DR);
endmodule
