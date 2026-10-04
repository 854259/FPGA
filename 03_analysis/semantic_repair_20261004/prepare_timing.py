"""Prepare prompt-only timing probes and freeze four archived checkpoints."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


TASKS = ["Prob045_edgedetect2", "Prob054_edgedetect", "Prob129_ece241_2013_q8", "Prob140_fsm_hdlc"]


def edge_tb(task, both):
    expression = "value ^ history" if both else "value & ~history"
    output = "anyedge" if both else "pedge"
    return f"""`timescale 1ns/1ps
module R2Probe;
 reg clk=0; reg [7:0] in=0; wire [7:0] {output};
 TopModule dut(.clk(clk),.in(in),.{output}({output}));
 integer checks=0, mismatches=0, i; reg [31:0] rng=32'h439fab12;
 reg [7:0] history=0, held=0, value;
 task check(input [7:0] expected);
 begin checks=checks+1; if ({output} !== expected) mismatches=mismatches+1; end endtask
 initial begin
  // Two sampled zeros establish history without constraining unspecified startup.
  #2; clk=1; #2; clk=0; #2; clk=1; #2; clk=0; #2;
  for (i=0;i<128;i=i+1) begin
   rng={{rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]}};
   case(i) 0:value=0; 1:value=255; 2:value=255; 3:value=0;
    4:value=85; 5:value=170; 6:value=128; 7:value=1; default:value=rng[7:0]; endcase
   in=~value; #1; check(held);
   in=value; #1; check(held);
   held={expression}; history=value;
   clk=1; #1; check(held); clk=0; #1; check(held);
  end
  $display("R2_PROBE_RESULT task={task} checks=%0d mismatches=%0d",checks,mismatches); $finish;
 end
endmodule
"""


MEALY_TB = """`timescale 1ns/1ps
module R2Probe;
 reg clk=0, aresetn=1, x=0; wire z;
 TopModule dut(.clk(clk),.aresetn(aresetn),.x(x),.z(z));
 integer checks=0,mismatches=0,state=0,i; reg value; reg [31:0] rng=32'h293a57b1;
 task check(input expected);
 begin checks=checks+1; if(z !== expected) mismatches=mismatches+1; end endtask
 initial begin
  #1; aresetn=0; #1; check(0); aresetn=1; #1; check(0);
  for(i=0;i<160;i=i+1) begin
   rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
   value=i<36 ? (i%3 != 1) : rng[0];
   x=~value; #1; check(state==2 && x);
   x=value; #1; check(state==2 && x);
   case(state) 0:state=x?1:0; 1:state=x?1:2; 2:state=x?1:0; endcase
   clk=1; #1; check(state==2 && x); clk=0; #1; check(state==2 && x);
  end
  $display("R2_PROBE_RESULT task=Prob129_ece241_2013_q8 checks=%0d mismatches=%0d",checks,mismatches); $finish;
 end
endmodule
"""


HDLC_TB = """`timescale 1ns/1ps
module R2Probe;
 reg clk=0,reset=1,in=0; wire disc,flag,err;
 TopModule dut(.clk(clk),.reset(reset),.in(in),.disc(disc),.flag(flag),.err(err));
 integer checks=0,mismatches=0,count=0,i,n; reg value; reg [2:0] held=0;
 reg [31:0] rng=32'h138af902;
 task check;
 begin checks=checks+1; if({disc,flag,err} !== held) mismatches=mismatches+1; end endtask
 task step(input sample,input rst);
 begin
  reset=rst; in=~sample; #1; check; in=sample; #1; check;
  if(rst) begin count=0; held=0; end
  else begin
   held[2]=(count==5 && !sample); held[1]=(count==6 && !sample);
   if(sample) begin if(count<7) count=count+1; end else count=0;
   held[0]=(count==7);
  end
  clk=1; #1; check; clk=0; #1; check;
 end endtask
 initial begin
  // Establish the specified synchronous reset before inspecting outputs.
  #1; clk=1; #1; clk=0; #1; reset=0;
  for(n=0;n<10;n=n+1) begin
   step(0,0); for(i=0;i<n;i=i+1) step(1,0); step(0,0);
  end
  for(i=0;i<128;i=i+1) begin
   rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]}; step(rng[0],i%37==0);
  end
  $display("R2_PROBE_RESULT task=Prob140_fsm_hdlc checks=%0d mismatches=%0d",checks,mismatches); $finish;
 end
endmodule
"""


MEALY_POS = """module TopModule(input clk,aresetn,x,output z);
 reg [1:0] state;
 always @(posedge clk or negedge aresetn)
  if(!aresetn) state<=0;
  else case(state) 0:state<=x?1:0; 1:state<=x?1:2; 2:state<=x?1:0; default:state<=0; endcase
 assign z=(state==2)&&x;
endmodule
"""
HDLC_POS = """module TopModule(input clk,reset,in,output reg disc,flag,err);
 reg [2:0] count;
 always @(posedge clk) begin
  if(reset) begin count<=0;disc<=0;flag<=0;err<=0; end
  else begin
   disc<=count==5&&!in; flag<=count==6&&!in; err<=in&&(count>=6);
   if(!in) count<=0; else if(count<7) count<=count+1'b1;
  end
 end
endmodule
"""


def prepare(prompts, candidates, out):
    out.mkdir(parents=True, exist_ok=False)
    for task in TASKS:
        folder = out / task
        folder.mkdir()
        shutil.copyfile(prompts / (task + "_prompt.txt"), folder / "prompt.txt")
        shutil.copyfile(candidates / task / "s0/solution.v", folder / "candidate.sv")
        if task in TASKS[:2]:
            both = task == TASKS[0]
            port = "anyedge" if both else "pedge"
            expr = "in ^ previous" if both else "in & ~previous"
            positive = f"module TopModule(input clk,input [7:0] in,output reg [7:0] {port});\n reg [7:0] previous;\n always @(posedge clk) begin {port}<={expr}; previous<=in; end\nendmodule\n"
            negative = f"module TopModule(input clk,input [7:0] in,output [7:0] {port});\n reg [7:0] previous;\n always @(posedge clk) previous<=in;\n assign {port}={expr};\nendmodule\n"
            tb, checks = edge_tb(task, both), 512
        elif task == TASKS[2]:
            positive = MEALY_POS
            negative = MEALY_POS.replace("output z", "output reg z").replace("assign z=(state==2)&&x;", "always @(posedge clk or negedge aresetn) if(!aresetn) z<=0; else z<=(state==2)&&x;")
            tb, checks = MEALY_TB, 642
        else:
            positive = HDLC_POS
            negative = HDLC_POS.replace("disc<=count==5&&!in; flag<=count==6&&!in; err<=in&&(count>=6);", "disc<=count==5; flag<=count==6; err<=count==7;")
            tb, checks = HDLC_TB, (sum(range(10)) + 20 + 128) * 4
        for name, content in (("tb.sv", tb), ("positive.sv", positive), ("negative.sv", negative)):
            (folder / name).write_text(content, encoding="utf-8", newline="\n")
        # Counts accompany the frozen probe; no oracle information enters model payloads.
        (folder / "contract.json").write_text(json.dumps(dict(task=task, checks=checks,
                    role="development_error" if task in TASKS[:2] else "correct_guard"), indent=2) + "\n")
    files = {str(p.relative_to(out)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in out.rglob("*") if p.is_file()}
    manifest = dict(schema="clocked_output_timing_pilot_v1", status="frozen_before_model_calls",
                    provenance="seven-rule full156 archive, 2026-10-02; not the best eight-rule score archive",
                    tasks=TASKS, real_model_call_budget=16, arms=["C_plain_review", "D_timing_contract_review"],
                    order=["D0", "C0", "C1", "D1"], temperature=0, top_p=1, max_tokens=8192,
                    trials_per_task_per_arm=2, retries=0, selection_scope="two known natural errors and two known correct guards",
                    acceptance="validated positive/semantic-negative controls, verified original checkpoints, no guard regression; pilot evidence only",
                    model_inputs="public prompt, frozen candidate, generic feedback skill and arm instruction only",
                    official_grading="only after all sixteen outputs are frozen", files=files,
                    limits=["tiny known development set; no held-out, full-set, initial-generation or end-to-end claim",
                            "no runtime adoption without broader independent evaluation"])
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompts", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.prompts, args.candidates, args.out)
