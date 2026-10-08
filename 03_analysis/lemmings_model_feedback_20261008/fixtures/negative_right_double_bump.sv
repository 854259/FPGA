// ARTIFICIAL QUALIFICATION ONLY; parameters fixed by the control designer.
module TopModule(input clk, areset, bump_left, bump_right, ground, dig,output walk_left, walk_right, aaah, digging);
  LfActivityControl #(.HAS_DIG(1),.HAS_DEATH(1),.FAULT(2)) fixture(.clk(clk),.areset(areset),.bump_left(bump_left),.bump_right(bump_right),.ground(ground),.dig(dig),.walk_left(walk_left),.walk_right(walk_right),.aaah(aaah),.digging(digging));
endmodule

// ARTIFICIAL QUALIFICATION FIXTURE ONLY. Not a generated competition answer.
// Independently hand-authored direction + activity model, entry0 convention.
// Never loaded by lemmings_feedback.py and never provided as a model answer.
module LfActivityControl #(
  parameter HAS_DIG=1, HAS_DEATH=1, FAULT=0
)(input clk, areset, bump_left, bump_right, ground, dig,
  output walk_left, walk_right, aaah, digging);
  localparam WALK=0, AIR=1, EXCAVATE=2, DEAD=3;
  integer activity;
  reg direction_right;
  integer completed_intervals;
  // Faults are isolated changes to one specified behaviour:
  // 1 synchronous reset; 2 R double-bump left-first; 3 L bump right-gated;
  // 4 direction exposed as walking; 5 exact20 dies; 6 5bit wrap;
  // 7 death while airborne; 8 no episode age reset; 9 dig loses to bump;
  // 10 bump wins over fall; 11 landing handles bump/dig a second time;
  // 12 dig stops when request drops; 13 direction changes while airborne;
  // 14 combinational input-dependent walking output; 15 dead revives;
  // 16 one output becomes X while falling; 17 reset not dominant on clock.
  task update_state;
    begin
      if (areset && !(FAULT==17 && clk)) begin
        activity <= WALK;
        direction_right <= 0;
        completed_intervals <= 0;
      end else begin
        case (activity)
          WALK: begin
            if (FAULT==10 && (direction_right ? bump_right : bump_left))
              direction_right <= ~direction_right;
            else if (!ground) begin
              activity <= AIR;
              if (FAULT!=8) completed_intervals <= 0;
            end else if (HAS_DIG && dig &&
                         !(FAULT==9 && (direction_right ? bump_right : bump_left)))
              activity <= EXCAVATE;
            else if (direction_right) begin
              if (FAULT==2 && bump_left) direction_right <= 1;
              else if (bump_right) direction_right <= 0;
            end else begin
              if (bump_left && (FAULT!=3 || bump_right)) direction_right <= 1;
            end
          end
          EXCAVATE: begin
            if (!ground) begin
              activity <= AIR;
              if (FAULT!=8) completed_intervals <= 0;
            end else if (FAULT==12 && !dig) activity <= WALK;
          end
          AIR: begin
            if (FAULT==13 && (direction_right ? bump_right : bump_left))
              direction_right <= ~direction_right;
            if (ground) begin
              if (HAS_DEATH &&
                  ((FAULT==6 ? ((completed_intervals+1) & 31) : completed_intervals+1)
                    > (FAULT==5 ? 19 : 20))) activity <= DEAD;
              else begin
                activity <= WALK;
                if (FAULT==11) begin
                  if (HAS_DIG && dig) activity <= EXCAVATE;
                  else if (direction_right ? bump_right : bump_left)
                    direction_right <= ~direction_right;
                end
              end
              if (FAULT==8) completed_intervals <= completed_intervals+1;
              else completed_intervals <= 0;
            end else begin
              if (FAULT==6) completed_intervals <= (completed_intervals+1) & 31;
              else completed_intervals <= completed_intervals+1;
              if (FAULT==7 && HAS_DEATH && completed_intervals+1>20)
                activity <= DEAD;
            end
          end
          DEAD: if (FAULT==15 && ground) activity <= WALK;
          default: activity <= WALK;
        endcase
      end
    end
  endtask
  generate
    if (FAULT==1) begin
      always @(posedge clk) update_state();
    end else begin
      always @(posedge clk or posedge areset) update_state();
    end
  endgenerate
  assign walk_left = (FAULT==16 && activity==AIR) ? 1'bx :
                     (FAULT==14 && !ground) ? 1'b0 :
                     ((FAULT==4 ? activity!=DEAD : activity==WALK) && !direction_right);
  assign walk_right = (FAULT==4 ? activity!=DEAD : activity==WALK) && direction_right;
  assign aaah = activity==AIR;
  assign digging = HAS_DIG && activity==EXCAVATE;
endmodule
