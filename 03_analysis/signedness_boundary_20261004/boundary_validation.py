"""AMD-only frozen boundary evaluation; no model generation requests."""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import importlib.util
import json
import signal
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")

def materials(case):
    w, s = case["width"], case["shift"]
    mask, sign = (1 << w) - 1, 1 << (w - 1)
    seeds = [0, 1, 2, mask, mask - 1, sign, sign - 1, sign + 1,
             int("55" * ((w + 7) // 8), 16), int("aa" * ((w + 7) // 8), 16),
             0x91d32f5b7a09e8c61, 0x74c2e9a105db6f38d]
    family = f"W{w}_S{s}" + ("_variable" if case.get("variable_amount") else "")
    extra_port = ", input [7:0] amt" if case.get("variable_amount") else ""
    extra_connection = f", .amt(8'd{s})" if case.get("variable_amount") else ""
    # A bit-index mapping, independent of the candidate's signed-shift operator.
    expression = "{" + ", ".join(f"q[{min(w - 1, bit + s)}]" for bit in reversed(range(w))) + "}"
    template = (f"module TopModule(input clk, input load, input [{w-1}:0] data{extra_port}, "
                f"output reg [{w-1}:0] q);\nalways @(posedge clk) "
                "if(load) q <= data; else q <= EXPR;\nendmodule\n")
    calls = "\n".join(f"step(1, {w}'h{value & mask:x}); repeat(3) step(0, 0);" for value in seeds)
    tb = f"""`timescale 1ns/1ps
module R2Probe;
reg clk=0, load=0;
reg [{w-1}:0] data=0, expected=0, next_expected;
wire [{w-1}:0] q;
integer checks=0, mismatches=0, bit_index;
TopModule dut(.clk(clk), .load(load), .data(data), .q(q){extra_connection});
task step;
 input next_load;
 input [{w-1}:0] next_data;
 begin
  clk=0; #2; load=next_load; data=next_data;
  if(next_load) expected=next_data;
  else begin
   for(bit_index=0; bit_index<{w}; bit_index=bit_index+1)
    if(bit_index+{s} < {w}) next_expected[bit_index]=expected[bit_index+{s}];
    else next_expected[bit_index]=expected[{w-1}];
   expected=next_expected;
  end
  #2; clk=1; #1;
  checks=checks+1;
  if(q !== expected) begin
   mismatches=mismatches+1;
   if(mismatches<=4) $display("BOUNDARY_MISMATCH n=%0d got=%h expected=%h",checks,q,expected);
  end
  #1; clk=0;
 end
endtask
initial begin
{calls}
$display("R2_PROBE_RESULT task={family} checks=%0d mismatches=%0d",checks,mismatches);
$finish;
end
endmodule
"""
    return family, tb, template.replace("EXPR", expression), template.replace("EXPR", "~(" + expression + ")")

def run(args):
    if sys.platform != "linux":
        raise RuntimeError("execute only on the authorized AMD host")
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        raise RuntimeError("cannot enable owned-child subreaper")
    paired = load("boundary_oracle_adapter", REPO / "03_analysis/selective_runtime_integration_20261003/paired_next/paired_checkpoint.py")
    spec = json.loads(args.spec.read_text())
    selector_path = REPO / "04_project/amd_rtl_agent/bench/signedness_selector.py"
    patch_path = REPO / "03_analysis/semantic_repair_20261004/signed_shift_patch.py"
    if sha(selector_path) != spec["selector_sha256"] or sha(patch_path) != spec["patch_sha256"]:
        raise RuntimeError("frozen selector/patch identity changed")
    selector, patcher = load("boundary_selector", selector_path), load("boundary_patch", patch_path)
    cases = json.loads(args.cases.read_text())["cases"]
    known = REPO / "03_analysis/r2_signedness_20261003"
    cases.insert(0, dict(id="Known115Wrong", cohort="development_reproduction",
                         prompt=(known / "input/Prob115_shift18/prompt.txt").read_text(),
                         source=(known / "input/Prob115_shift18/candidate.sv").read_text(),
                         expected_before="fail", expected_action="change"))
    assets = [args.spec.resolve(), args.cases.resolve(), Path(__file__).resolve()]
    assets += [selector_path, patch_path, Path(paired.__file__), paired.INHERITED_ORACLE,
               known / "input/Prob115_shift18/prompt.txt", known / "input/Prob115_shift18/candidate.sv"]
    assets += [known / "probes/Prob115_shift18" / name for name in ("tb.sv", "positive.sv", "negative.sv")]
    frozen = {str(p.relative_to(REPO)): sha(p) for p in assets}
    paired.check_resource(args.resource_check, args.kit, first=True)
    args.out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = dict(schema="signedness_boundary_result_v1", complete=False, evidence_valid=False,
                  adoption_accepted=False, model_calls=0, input_hashes=frozen, rows=[], controls={})
    try:
        tasks = {"Prob115_shift18":dict(task="Prob115_shift18", checks=31,
                   tb=str(known / "probes/Prob115_shift18/tb.sv"),
                   positive=str(known / "probes/Prob115_shift18/positive.sv"),
                   negative=str(known / "probes/Prob115_shift18/negative.sv"))}
        # Freeze all generated testbenches and both deterministic transformations before scoring.
        for case in cases:
            if case["cohort"] == "development_reproduction":
                family = "Prob115_shift18"
            else:
                family, tb, positive, negative = materials(case)
                if family not in tasks:
                    folder = args.out / "materials" / family
                    folder.mkdir(parents=True)
                    for name, text in (("tb.sv",tb),("positive.sv",positive),("negative.sv",negative)):
                        (folder / name).write_text(text, encoding="utf-8")
                    tasks[family]=dict(task=family, checks=48, tb=str(folder/"tb.sv"),
                                       positive=str(folder/"positive.sv"),negative=str(folder/"negative.sv"))
            tick = time.perf_counter()
            updated, receipt = patcher.patch(case["prompt"],case["source"],selector)
            transform_s = time.perf_counter() - tick
            duplicate, duplicate_receipt = patcher.patch(case["prompt"],case["source"],selector)
            again, again_receipt = patcher.patch(case["prompt"],updated,selector)
            folder = args.out / "candidates" / case["id"]
            folder.mkdir(parents=True)
            (folder/"before.sv").write_text(case["source"],encoding="utf-8")
            (folder/"after.sv").write_text(updated,encoding="utf-8")
            report["rows"].append(dict(id=case["id"],cohort=case["cohort"],family=family,
                expected_before=case["expected_before"],expected_action=case["expected_action"],
                transformation=receipt,transform_s=transform_s,byte_identical=updated==case["source"],
                repeat_identical=duplicate==updated and duplicate_receipt==receipt,
                idempotent=again==updated and not again_receipt["changed"],
                before_source_sha256=sha(folder/"before.sv"),after_source_sha256=sha(folder/"after.sv")))
        generated = {str(p.relative_to(args.out)):sha(p) for top in ("candidates","materials")
                     for p in sorted((args.out/top).rglob("*.sv"))}
        save(args.out/"transformations_frozen.json",dict(rows=report["rows"],generated=generated,input_hashes=frozen))
        for family, task in tasks.items():
            control = {name:paired.oracle(task,Path(task[name]),args.out/"controls"/family/name)
                       for name in ("positive","negative")}
            control["valid"]=(control["positive"]["status"]=="pass" and
                              control["negative"]["status"]=="fail" and
                              control["negative"]["failure_kind"]=="semantic_mismatch")
            report["controls"][family]=control
            if not control["valid"]:
                raise RuntimeError("control_invalid: "+family)
        for row in report["rows"]:
            paired.check_resource(args.resource_check,args.kit)
            if any(sha(REPO/path)!=digest for path,digest in frozen.items()):
                raise RuntimeError("frozen source changed")
            folder=args.out/"candidates"/row["id"]
            task=tasks[row["family"]]
            row["before"]=paired.oracle(task,folder/"before.sv",args.out/"grades"/row["id"]/"before")
            if row["before"]["status"]=="environment_error":
                raise RuntimeError("before_environment_error: "+row["id"])
            if row["before"]["status"]=="fail" and row["before"]["failure_kind"]!="semantic_mismatch":
                raise RuntimeError("before_not_a_semantic_result: "+row["id"])
            if row["byte_identical"]:
                row["after"]=dict(row["before"])
                row["after_reuses_identical_before_receipt"]=True
            else:
                row["after"]=paired.oracle(task,folder/"after.sv",args.out/"grades"/row["id"]/"after")
            if row["after"]["status"]=="environment_error":
                raise RuntimeError("after_environment_error: "+row["id"])
            if row["after"]["status"]=="fail" and row["after"]["failure_kind"]!="semantic_mismatch":
                raise RuntimeError("after_not_a_semantic_result: "+row["id"])
            statuses=(row["before"]["status"],row["after"]["status"])
            row.update(repair=statuses==("fail","pass"),regression=statuses==("pass","fail"),
                       oracle_expected_before=row["before"]["status"]==row["expected_before"],
                       action_expected=row["transformation"]["changed"]==(row["expected_action"]=="change"))
            row["accepted"]=(row["oracle_expected_before"] and row["action_expected"] and
                             row["repeat_identical"] and row["idempotent"] and not row["regression"] and
                             (row["repair"] if row["expected_action"]=="change" else row["byte_identical"]))
            save(args.out/"rows"/(row["id"]+".json"),row)
            print(json.dumps({k:row[k] for k in ("id","cohort","repair","regression","accepted")}),flush=True)
        report["complete"]=True
        report["generated_inputs_unchanged"]=all(sha(args.out/path)==digest for path,digest in generated.items())
        report["evidence_valid"]=(report["generated_inputs_unchanged"] and
                                  all(r["oracle_expected_before"] for r in report["rows"]))
        report["adoption_accepted"]=report["evidence_valid"] and all(r["accepted"] for r in report["rows"])
    except BaseException as exc:
        report["error"]=type(exc).__name__+": "+str(exc)
    finally:
        report["elapsed_s"]=time.monotonic()-started
        report["source_unchanged"]=all(sha(REPO/path)==digest for path,digest in frozen.items())
        report["evidence_valid"]=report["evidence_valid"] and report["source_unchanged"]
        report["cohorts"]={cohort:dict(cases=len(rows),scored=sum("after" in r for r in rows),
                    repairs=sum(r.get("repair",False) for r in rows),
                    regressions=sum(r.get("regression",False) for r in rows),
                    changed=sum(r["transformation"]["changed"] for r in rows),
                    preserved=sum(r["byte_identical"] for r in rows))
              for cohort in sorted({r["cohort"] for r in report["rows"]})
              for rows in [[r for r in report["rows"] if r["cohort"]==cohort]]}
        report["decision"]=("retain_for_further_validation" if report["adoption_accepted"]
                            else "reject_current_auto_patch" if report["evidence_valid"] else "inconclusive")
        save(args.out/"summary.json",report)
        print(json.dumps({k:report[k] for k in ("complete","evidence_valid","adoption_accepted","cohorts","decision","elapsed_s")}),flush=True)
    return 0 if report["complete"] and report["evidence_valid"] else 1

if __name__=="__main__":
    sys.dont_write_bytecode=True
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("out","resource-check","kit"):
        p.add_argument("--"+name,type=Path,required=True)
    p.add_argument("--spec",type=Path,default=HERE/"RUN_SPEC.json")
    p.add_argument("--cases",type=Path,default=HERE/"cases.json")
    args=p.parse_args()
    def cancelled(sig,frame):
        raise InterruptedError("owned boundary stage cancelled")
    for sig in (signal.SIGTERM,signal.SIGINT):
        signal.signal(sig,cancelled)
    raise SystemExit(run(args))
