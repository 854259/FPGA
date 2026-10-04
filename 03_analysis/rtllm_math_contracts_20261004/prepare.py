"""Freeze a clear four-task RTLLM subset and independent exhaustive oracles."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT.parent / "natural_coverage_20261004/raw_evidence/inputs/rtllm_g2"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build(task):
    cmp_width = {"comparator_3bit": 3, "comparator_4bit": 4}.get(task)
    if cmp_width:
        w = cmp_width
        header = f"module TopModule(input [{w-1}:0] A,B, output A_greater,A_equal,A_less);\n"
        if w == 4:
            positive = header + "wire [4:0] difference={1'b0,A}-{1'b0,B};\nassign A_less=difference[4]; assign A_equal=(A==B); assign A_greater=!A_less&&!A_equal;\nendmodule\n"
        else:
            positive = header + "assign A_greater=(A>B); assign A_equal=(A==B); assign A_less=(A<B);\nendmodule\n"
        negative = header + f"assign A_greater=(A[{w-2}:0]>B[{w-2}:0]); assign A_equal=(A[{w-2}:0]==B[{w-2}:0]); assign A_less=(A[{w-2}:0]<B[{w-2}:0]);\nendmodule\n"
        declarations = f"reg [{w-1}:0] A,B; wire A_greater,A_equal,A_less;\nTopModule dut(.A(A),.B(B),.A_greater(A_greater),.A_equal(A_equal),.A_less(A_less));\ninteger a_index,b_index;reg [2:0] expected;"
        loop = f"for(a_index=0;a_index<{2**w};a_index=a_index+1) for(b_index=0;b_index<{2**w};b_index=b_index+1) begin\nA=a_index;B=b_index;#1;expected={{(a_index>b_index),(a_index==b_index),(a_index<b_index)}};check_result({{A_greater,A_equal,A_less}},expected);end"
        checks = 2**(2*w)
        scope = "All two-state unsigned operand pairs, packed greater/equal/less output; no X/Z semantics claim"
    elif task == "adder_8bit":
        header = "module TopModule(input [7:0] a,b,input cin,output [7:0] sum,output cout);\n"
        positive = header + "wire [8:0] carry;assign carry[0]=cin;genvar i;generate for(i=0;i<8;i=i+1)begin assign sum[i]=a[i]^b[i]^carry[i];assign carry[i+1]=(a[i]&b[i])|(a[i]&carry[i])|(b[i]&carry[i]);end endgenerate assign cout=carry[8];endmodule\n"
        negative = header + "assign sum=a+b+cin;assign cout=1'b0;endmodule\n"
        declarations = "reg [7:0] a,b;reg cin;wire [7:0] sum;wire cout;TopModule dut(.a(a),.b(b),.cin(cin),.sum(sum),.cout(cout));integer a_index,b_index,c_index;reg [8:0] expected;"
        loop = "for(a_index=0;a_index<256;a_index=a_index+1) for(b_index=0;b_index<256;b_index=b_index+1)for(c_index=0;c_index<2;c_index=c_index+1)begin a=a_index;b=b_index;cin=c_index;#1;expected=a_index+b_index+c_index;check_result({cout,sum},expected);end"
        checks = 131072
        scope = "All 8-bit unsigned operands and both carry-in values, checks all 9 output bits; full-adder positive vs integer-add oracle"
    else:
        assert task == "multi_8bit"
        header = "module TopModule(input [7:0] A,B,output reg [15:0] product);\n"
        positive = header + "integer i;always @* begin product=0;for(i=0;i<8;i=i+1)if(B[i])product=product+({8'b0,A}<<i);end endmodule\n"
        negative = header + "always @* product=(A*B)&16'h00ff;endmodule\n"
        declarations = "reg [7:0] A,B;wire [15:0] product;TopModule dut(.A(A),.B(B),.product(product));integer a_index,b_index;reg [15:0] expected;"
        loop = "for(a_index=0;a_index<256;a_index=a_index+1)for(b_index=0;b_index<256;b_index=b_index+1)begin A=a_index;B=b_index;#1;expected=a_index*b_index;check_result(product,expected);end"
        checks = 65536
        scope = "All two-state 8-bit unsigned operand pairs, full 16-bit product; shift/add positive vs integer-product oracle"
    tb = f'''`timescale 1ns/1ps
module R2Probe;
{declarations}
integer checks=0,mismatches=0;
task check_result(input [31:0] observed,input [31:0] expected_value);
begin checks=checks+1;if(observed!==expected_value)begin
if(mismatches==0)$display("FIRST_MISMATCH observed=%h expected=%h",observed,expected_value);
mismatches=mismatches+1;end end endtask
initial begin {loop}
$display("R2_PROBE_RESULT task={task} checks=%0d mismatches=%0d",checks,mismatches);
if(checks!={checks})$fatal(1,"CHECK_COUNT_INVALID");$finish;end
initial begin #1000000;$fatal(1,"WATCHDOG_EXPIRED");end
endmodule
'''
    return positive, negative, tb, checks, scope


def main():
    contracts = []
    for task in ("comparator_3bit", "comparator_4bit", "adder_8bit", "multi_8bit"):
        folder = ROOT / "inputs" / task
        folder.mkdir(parents=True, exist_ok=False)
        original = (ARCHIVE / "agent" / task / "prompt.txt").read_text(encoding="utf-8")
        prompt = re.sub(r"Module name:\s*adder_8bit\b", "Module name: TopModule", original)
        # Remove only the redundant leading declaration when the body now names TopModule.
        if task == "adder_8bit":
            assert prompt.startswith("Module name: TopModule\n\n")
            prompt = prompt[len("Module name: TopModule\n\n"):]
        assert len(re.findall(r"Module name:", prompt)) == 1
        (folder / "prompt.original.txt").write_bytes((ARCHIVE / "agent" / task / "prompt.txt").read_bytes())
        (folder / "prompt.txt").write_text(prompt, encoding="utf-8", newline="\n")
        for side in ("agent", "baseline"):
            (folder / (side + ".sv")).write_bytes((ARCHIVE / side / task / "candidate.sv").read_bytes())
        positive, negative, tb, checks, scope = build(task)
        for name, text in (("positive.sv", positive), ("negative.sv", negative), ("tb.sv", tb)):
            (folder / name).write_text(text, encoding="utf-8", newline="\n")
        contracts.append(dict(task=task, checks=checks, scope=scope, prompt_changed=prompt != original,
            change="Only duplicate/conflicting module-name declaration corrected" if task == "adder_8bit" else "none"))
    dependencies = ROOT.parent / "ross_diagnostic_repair_20261004"
    depnames = ("paired_checkpoint.py", "probe_runner.py")
    assets = [p for p in ROOT.rglob("*") if p.is_file() and p.suffix in (".py", ".sv", ".txt")]
    spec = dict(schema="rtllm_four_math_contracts_v1", status="frozen_before_eda", base_commit=subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip(),
        contracts=contracts, source_hashes={p.relative_to(ROOT).as_posix():sha(p) for p in assets},
        dependency_hashes={n:sha(dependencies/n) for n in depnames},
        dependencies_cloud="/workspace/team/runs/fpga_owner/ross_diagnostic_repair_20261004_v1",
        source_archive_sha256="c35e8c7e8a1c699aea6028cf3774f7b1797d52015a553440a49eb7d90cf8cfcc",
        resource_guard_sha256="59c4212cb77971406255690c0efab0593cb5c100b21cf9d22622a9917be5e66d",
        model_calls=0, part="xczu3eg-sbva484-1-e", timeout_s=1200,
        acceptance="Each positive completes exact exhaustive checks without mismatch and synthesizes; each task-specific negative fails semantically. All original 8 candidate results reported, no filtering or reprompting. Guard gates pass.",
        limits=["This is a small cross-source reliable contract substrate, not a new whole RTLLM score or independent natural validation of B2.","Tasks are known public RTLLM tasks; old 8 candidates remain byte-identical, adder prompt correction cannot be retroactively attributed to those generations.","Unsigned two-state finite combinational domain only; implementation algorithm not formally proven from simulation; X/Z and timing/resource quality unmeasured.","No reference/TB/grades sent to a model; zero new inference. Historical reference/TB and aggregates unchanged."])
    (ROOT / "RUN_SPEC.json").write_text(json.dumps(spec,indent=2)+"\n",encoding="utf-8",newline="\n")
    with zipfile.ZipFile(ROOT / "source_transfer.zip", "x", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(ROOT.rglob("*")):
            if p.is_file() and p.suffix != ".zip" and "__pycache__" not in p.parts:
                z.write(p,p.relative_to(ROOT).as_posix())
    print(json.dumps(dict(checks_per_complete_probe=sum(c["checks"] for c in contracts),transfer_sha256=sha(ROOT/"source_transfer.zip"))))


if __name__ == "__main__":
    main()
