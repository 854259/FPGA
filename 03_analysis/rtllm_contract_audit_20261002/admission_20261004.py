"""AMD-only whole-inventory RTLLM fixture admission; no model generation.

Private oracle bodies are supplied separately and never included in solver inputs.
This is a dataset admission substage, not a complete model-quality experiment.
"""
import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BASE = Path("/workspace/team/runs/fpga_teammate")
H1 = BASE / "helper_H1_20261004T054811Z_e144197/results"
LABEL = re.compile(r"Module\s+name\s*[:：]\s*([A-Za-z_]\w*)", re.I)

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def canonical_prompt(text):
    text = text.replace("\r\n", "\n")
    labels = LABEL.findall(text)
    if len(labels) == 2:
        assert text.startswith("Module name: TopModule\n\n")
        text = text[len("Module name: TopModule\n\n"):]
    assert len(LABEL.findall(text)) == 1
    return LABEL.sub("Module name: NAME", text)

def material(case, source):
    ports = case["ports"]
    params = case.get("parameters", {})
    bind = "#(" + ",".join(f".{k}({v})" for k,v in params.items()) + ")" if params else ""
    decl = "\n".join(f"{'reg' if d=='input' else 'wire'} {w} {n};" for d,n,w in ports)
    connection = ",".join(f".{n}({n})" for _,n,_ in ports)
    tb = ("\x60timescale 1ns/1ps\nmodule tb;\n" + decl +
          "\ninteger errors=0,samples=0;\nTopModule " + bind + " dut(" + connection + ");\n" +
          case.get("instances", "") +
          '\ntask check(input logic ok); begin samples=samples+1; if(ok !== 1\'b1) begin errors=errors+1; if(errors<=5) $display("CHECK_FAIL sample=%0d time=%0t",samples,$time); end end endtask\n' +
          'initial begin : stimulus\n' + case["body"] +
          '\n$display("ADMISSION_RESULT errors=%0d samples=%0d",errors,samples);\n' +
          '$display("Mismatches: %1d in %1d samples",errors,samples); $finish; end\n' +
          'initial begin #12000000; $fatal(1,"ADMISSION_WATCHDOG"); end\nendmodule\n')
    core = re.sub(r"\bTopModule\b", "AdmissionNegativeCore", source)
    header = "module TopModule"
    if params:
        header += " #(" + ",".join(f"parameter {k}={v}" for k,v in params.items()) + ")"
    header += "(" + ",".join(n for _,n,_ in ports) + ");\n"
    declarations = [f"{d} {w} {n};" for d,n,w in ports]
    outputs = [(n,w) for d,n,w in ports if d == "output"]
    wires = [f"wire {w} internal_{n};" for n,w in outputs]
    connections = [f".{n}(" + ("internal_"+n if d=="output" else n) + ")" for d,n,_ in ports]
    forward = "#(" + ",".join(f".{k}({k})" for k in params) + ")" if params else ""
    assigns = [f"assign {n} = " + ("~" if i==0 else "") + f"internal_{n};" for i,(n,_) in enumerate(outputs)]
    negative = core + "\n" + header + "\n".join(declarations+wires+[
        "AdmissionNegativeCore "+forward+" core("+",".join(connections)+");"]+assigns)+"\nendmodule\n"
    return tb, negative

def simulate(case, label, source, tb, out, paired, toolbin):
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(source, out/"candidate.sv")
    shutil.copyfile(tb, out/"tb.sv")
    commands = [
        ("xvlog", [str(toolbin/"xvlog"), "--sv", "candidate.sv", "tb.sv"], 30),
        ("xelab", [str(toolbin/"xelab"), "tb", "-s", "admission", "--mt", "off"], 45),
        ("xsim", [str(toolbin/"xsim"), "admission", "--runall"], 60)]
    result = dict(label=label, valid=False, stages=[], source_sha256=sha(source), tb_sha256=sha(tb))
    for name,cmd,cap in commands:
        receipt = paired.owned_command(cmd,out,out/(name+".log"),cap)
        result["stages"].append(dict(name=name,**receipt))
        save(out/"execution.json",result)
        if receipt.get("timeout") or receipt.get("launch_error") or receipt.get("remaining_live_group"):
            raise RuntimeError(f"environment or owned-process failure {case['name']}/{label}/{name}")
        if receipt["returncode"] != 0:
            result.update(reason=name+"_failed",compile_or_fixture_failure=True)
            break
    else:
        text = (out/"xsim.log").read_text(errors="replace")
        matches = re.findall(r"ADMISSION_RESULT errors=(\d+) samples=(\d+)",text)
        if len(matches) != 1 or "ADMISSION_WATCHDOG" in text:
            raise RuntimeError("missing or inconsistent simulation completion marker")
        errors,samples = map(int,matches[0])
        result.update(valid=samples >= case["minimum_checks"],errors=errors,samples=samples,
                      reason="completed" if samples>=case["minimum_checks"] else "insufficient_observations")
    save(out/"execution.json",result)
    # Preserve source, logs, execution receipts and hashes before removing reproducible build data.
    hashes = {str(p.relative_to(out)):sha(p) for p in out.rglob("*") if p.is_file() and not any(
        x in p.parts for x in ("xsim.dir",".Xil","__pycache__")) and p.name!="archive_manifest.json"}
    archive = out.parent/(out.name+"-evidence.zip")
    with zipfile.ZipFile(archive,"x",zipfile.ZIP_DEFLATED) as z:
        for rel in hashes: z.write(out/rel,rel)
    with zipfile.ZipFile(archive) as z:
        assert all(hashlib.sha256(z.read(rel)).hexdigest()==h for rel,h in hashes.items())
    removed=[]
    for dirname in ("xsim.dir",".Xil","__pycache__"):
        for p in list(out.rglob(dirname)):
            if not p.exists(): continue
            assert p.resolve().is_relative_to(out.resolve()) and not p.is_symlink()
            removed.append(str(p.relative_to(out)));shutil.rmtree(p)
    save(out/"archive_manifest.json",dict(files=hashes,archive_sha256=sha(archive),removed_cache_dirs=removed))
    return result

def run(args):
    assert sys.platform=="linux" and ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
    spec=json.loads((HERE/"ADMISSION_SPEC_20261004.json").read_text())
    assert sha(args.controls)==spec["private_controls_sha256"]
    private=json.loads(args.controls.read_text())
    assert [x["name"] for x in private["cases"]]==spec["new_control_tasks"]
    assert len(private["cases"])==20
    assert sha(H1/"DATASET_MANIFEST.json")==spec["h1_manifest_sha256"]
    original=json.loads((H1/"DATASET_MANIFEST.json").read_text())["files"]
    frozen={H1/"tasks_contract_v1"/p:h for p,h in original.items()}
    assert all(sha(p)==h for p,h in frozen.items())
    paired=load("admission_paired",REPO/"03_analysis/selective_runtime_integration_20261003/paired_next/paired_checkpoint.py")
    paired.check_resource(args.resource_check,args.kit,first=True)
    toolbin=Path(os.environ["VIVADO_BIN"])
    assert all((toolbin/n).is_file() for n in ("xvlog","xelab","xsim"))
    args.out.mkdir(parents=True,exist_ok=False)
    tick=time.monotonic()
    report=dict(schema="rtllm_whole_inventory_admission",complete=False,full_experiment_complete=False,
        model_calls=0,candidate_scores=[],new_controls=[],reused_controls=[],blocked=spec["blocked"],
        source_commit=(REPO/"DELIVERY_COMMIT").read_text().strip(),error=None)
    def publish(phase):
        report.update(phase=phase,elapsed_s=time.monotonic()-tick)
        save(args.out/"summary.json",report)
        print(json.dumps(dict(phase=phase,elapsed_s=report["elapsed_s"],
              controls_done=len(report["new_controls"]),model_calls=0)),flush=True)
    def gate():
        assert sha(args.controls)==spec["private_controls_sha256"]
        assert all(sha(p)==h for p,h in frozen.items())
        paired.check_resource(args.resource_check,args.kit)
        paired.model_idle("http://127.0.0.1:8000/v1","Qwen3.6-27B-Q4_K_M")
        if shutil.disk_usage(args.out).free < 3*1024**3:raise RuntimeError("disk reserve exhausted")
        if time.monotonic()-tick>spec["stop_new_work_after_s"]:raise TimeoutError("new work reserve exhausted")
    try:
        tasks=args.out/"tasks_admission_v2"
        shutil.copytree(H1/"tasks_contract_v1",tasks)
        # Reuse verified historical fixture bytes, preserving H1's normalized prompt.
        for run in spec["historical"]:
            root=BASE/run["run"]
            assert sha(root/"manifest.json")==run["manifest_sha256"]
            manifest=json.loads((root/"manifest.json").read_text())
            for section,base in (("immutable_sha256",BASE/"rtllm_pair_20261002T074340Z"),("prepared_sha256",root)):
                for rel,h in manifest[section].items():
                    assert sha(base/rel)==h,(run["run"],rel)
                    frozen[base/rel]=h
            for name in run["tasks"]:
                old=root/"tasks"/name
                assert canonical_prompt((old/"prompt.txt").read_text())==canonical_prompt((tasks/name/"prompt.txt").read_text()),name
                files={}
                for rel in ("ref.sv","tb.sv","reference/solution.sv","task.json"):
                    shutil.copyfile(old/rel,tasks/name/rel);files[rel]=sha(old/rel)
                report["reused_controls"].append(dict(task=name,source_run=run["run"],files=files,
                    scope="historically verified finite domain; no new model or EDA; not universal contract proof"))
        report["reused_controls"].append(dict(task="barrel_shifter",source_run=H1.parent.name,
            scope="H1 exhaustive 2048 default inputs; no rerun",files={p:sha(tasks/"barrel_shifter"/p)
            for p in ("ref.sv","tb.sv","reference/solution.sv","task.json")}))
        controls=args.out/"private_controls";controls.mkdir()
        for case in private["cases"]:
            name=case["name"];folder=tasks/name
            tb,negative=material(case,(folder/"reference/solution.sv").read_text())
            (folder/"tb.sv").write_text(tb)
            (controls/(name+"_negative.sv")).write_text(negative)
        new_hashes={str(p.relative_to(tasks)):sha(p) for p in sorted(tasks.rglob("*")) if p.is_file()}
        save(args.out/"DATASET_MANIFEST.json",dict(version="rtllm_admission_v2_20261004",
            files=new_hashes,original_denominator=44,model_calls=0,candidate_scores_available=False,
            old_dataset_modified=False,private_controls_sha256=spec["private_controls_sha256"],
            reused=report["reused_controls"],blocked=spec["blocked"],new_control_tasks=spec["new_control_tasks"]))
        # All inputs are frozen before any dynamic observations. No adaptation or resampling.
        publish("dataset_frozen")
        for case in private["cases"]:
            gate()
            name=case["name"];folder=tasks/name
            row=dict(task=name,scope=case["scope"],minimum_checks=case["minimum_checks"],arms={})
            report["new_controls"].append(row)
            for label,src in (("positive",folder/"reference/solution.sv"),("negative",controls/(name+"_negative.sv"))):
                gate()
                row["arms"][label]=simulate(case,label,src,folder/"tb.sv",args.out/"controls"/name/label,paired,toolbin)
                publish(name+"_"+label)
            p,n=row["arms"]["positive"],row["arms"]["negative"]
            row["passed"]=p.get("valid") is True and p.get("errors")==0 and n.get("valid") is True and n.get("errors",0)>0
            row["decision"]="finite_domain_controls_passed" if row["passed"] else "fixture_or_reference_diagnosis_required"
            # Admission failures are recorded for every task, never counted as model failures.
            publish("qualified_"+name if row["passed"] else "blocked_"+name)
        gate()
        assert all(sha(tasks/p)==h for p,h in new_hashes.items())
        report.update(complete=True,execution_valid=True,frozen_inputs_unchanged=True,
            new_controls_passed=sum(x["passed"] for x in report["new_controls"]),
            inventory_tasks=44,reused_tasks=len(report["reused_controls"]),
            full_contracts_certified=False,quality_gain_established=False,
            architecture_and_unlisted_parameters_certified=False)
        publish("admission_inventory_completed")
    except BaseException as e:
        report["error"]=type(e).__name__+": "+str(e)
        raise
    finally:
        publish("finished" if report["complete"] else "failed")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for name in ("kit","out","resource-check","controls"):
        parser.add_argument("--"+name,type=Path,required=True)
    run(parser.parse_args())

