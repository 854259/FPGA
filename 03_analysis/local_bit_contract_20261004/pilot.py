"""Three-arm local-contract study; execute only through the existing AMD guard."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import time
import urllib.request

from feedback import messages

MODEL="Qwen3.6-27B-Q4_K_M"
ENDPOINT="http://127.0.0.1:8000/v1"
SYSTEM="You review synthesizable RTL. Use the supplied public specification as the authority."
COMMON=("Review the candidate against the full specification. Correct functional errors with "
        "a focused edit, preserve the interface and required timing, and add no unsupported "
        "reset or initialization. If it already meets the specification, return it unchanged. "
        "Return only one complete synthesizable TopModule, without explanations or a testbench.")
TASK="Prob108_rule90"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path,data):
    Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module);return module


def main():
    ap=argparse.ArgumentParser()
    for name in ("root","dependencies","kit","resource-check"):
        ap.add_argument("--"+name,type=Path,required=True)
    args=ap.parse_args();root=args.root.resolve();deps=args.dependencies.resolve();kit=args.kit.resolve()
    assert ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
    spec=read(root/"RUN_SPEC.json");spec_hash=sha(root/"RUN_SPEC.json")
    for f,h in spec["dependency_hashes"].items():assert sha(deps/f)==h,f
    for f,h in spec["source_hashes"].items():assert sha(root/f)==h,f
    paired=load("local_contract_owned",deps/"paired_checkpoint.py")
    paired.REPO=root;paired.INHERITED_ORACLE=deps/"probe_runner.py"
    baseline=load("local_contract_extract",deps/"baseline_extract.py")
    evaluator=load("local_contract_official",deps/"official_eval.py")
    evaluator.ROOT=kit;evaluator.OFFICIAL=kit/"official_reference"
    assert evaluator.verify_upstream()==spec["official_commit"]
    paired.check_resource(args.resource_check,kit,first=True)
    out=root/"results";out.mkdir(exist_ok=False);started=time.monotonic()
    report=dict(schema="local_bit_contract_pilot_v1",complete=False,verified=False,
        attempts=0,responses=0,retries=0,controls={},originals={},rows=[],run_spec_sha256=spec_hash,
        dependency_root=str(deps),model=MODEL,new_score=False,formal_runtime_integrated=False)
    save(out/"summary.json",report)

    def frozen():
        assert time.monotonic()-started<spec["max_stage_elapsed_s"]
        assert sha(root/"RUN_SPEC.json")==spec_hash
        for f,h in spec["source_hashes"].items():assert sha(root/f)==h,f
        for f,h in spec["dependency_hashes"].items():assert sha(deps/f)==h,f
        paired.check_resource(args.resource_check,kit)

    def probe(source,destination):
        frozen();r=paired.oracle(dict(task=TASK,checks=spec["checks"],tb="inputs/"+TASK+"/tb.sv"),source,destination)
        if r["status"]=="environment_error":raise RuntimeError("XSim environment failure")
        return r

    def grade(source,destination):
        frozen();destination.mkdir(parents=True,exist_ok=False)
        r=evaluator.judge_sample(kit/"bench/tasks_veval"/TASK,source,destination,destination/"verdict.json",120)
        if r.get("tool_error") or r.get("suspected_silent_degradation"):raise RuntimeError("Official tool/environment failure")
        return r

    try:
        directory=root/"inputs"/TASK
        controls={name:probe(directory/(name+".sv"),out/"controls"/name) for name in ("positive","negative")}
        assert controls["positive"]["status"]=="pass" and controls["negative"]["failure_kind"]=="semantic_mismatch"
        report["controls"]=controls
        for subject in spec["subjects"]:
            source=root/subject["source"];original=probe(source,out/"original_probes"/subject["id"])
            text=(out/"original_probes"/subject["id"]/"xsim.log").read_text(encoding="utf-8",errors="replace")
            first=[x for x in text.splitlines() if x.startswith("FIRST_MISMATCH")]
            assert len(first)==(1 if subject["role"]=="development_error" else 0)
            assert original["checks"]==spec["checks"] and original["mismatches"]==subject["expected_mismatches"]
            feedback=messages(original["checks"],original["mismatches"],first[0] if first else None)
            if feedback["normalized"]:
                witness=feedback["normalized"]
                assert witness["time_ps"]==5000 and witness["load"]==0 and witness["data_set_bits"]==[]
                assert witness["previous_set_bits"]==[0] and witness["bit"]==0 and witness["expected"]==0 and witness["observed"]==1
            official=grade(source,out/"official_originals"/subject["id"])
            assert (official["level"]==3)==(subject["role"]=="correct_guard")
            report["originals"][subject["id"]]=dict(probe=original,official=official,feedback=feedback)
            save(out/"summary.json",report)
            print(json.dumps(dict(phase="original_verified",subject=subject["id"],mismatches=original["mismatches"],official_level=official["level"])),flush=True)
        save(out/"preflight_verified.json",dict(controls=controls,originals=report["originals"],model_calls=0))
        prompt=(directory/"prompt.txt").read_text(encoding="utf-8")
        for subject in spec["subjects"]:
            original_source=root/subject["source"];candidate=original_source.read_text(encoding="utf-8")
            for label in spec["order"]:
                frozen();paired.model_idle(ENDPOINT,MODEL)
                assert report["attempts"]<spec["model_call_budget"]
                folder=out/"generated"/subject["id"]/label;folder.mkdir(parents=True)
                user="Specification:\n"+prompt+"\nCandidate:\n"+candidate+"\n\n"+COMMON+"\n\nObserved diagnostic:\n"+report["originals"][subject["id"]]["feedback"][label[0]]
                payload=dict(model=MODEL,temperature=0,top_p=1,max_tokens=spec["max_tokens"],messages=[dict(role="system",content=SYSTEM),dict(role="user",content=user)])
                body=json.dumps(payload,ensure_ascii=False).encode("utf-8");(folder/"request.json").write_bytes(body)
                row=dict(subject=subject["id"],role=subject["role"],label=label,request_sha256=sha(folder/"request.json"),response_received=False)
                report["rows"].append(row);report["attempts"]+=1;save(out/"summary.json",report)
                tick=time.monotonic();request=urllib.request.Request(ENDPOINT+"/chat/completions",data=body,headers={"Content-Type":"application/json"})
                with urllib.request.urlopen(request,timeout=spec["request_timeout_s"]) as response:raw=response.read()
                (folder/"response.json").write_bytes(raw);response=json.loads(raw);choice=response["choices"][0]
                row.update(response_received=True,request_elapsed_s=time.monotonic()-tick,response_sha256=sha(folder/"response.json"),response_id=response.get("id"),usage=response.get("usage"),finish_reason=choice.get("finish_reason"),cache_or_timings={k:v for k,v in response.items() if "cache" in k.lower() or k=="timings"} or "unknown")
                report["responses"]+=1;content=choice["message"].get("content")
                if choice.get("finish_reason")!="stop" or not isinstance(content,str) or not content.strip():raise RuntimeError("Truncated/empty response; stop without retry")
                (folder/"answer.txt").write_text(content,encoding="utf-8")
                solution=folder/"solution.v";solution.write_text(baseline.extract(content,"rtl"),encoding="utf-8")
                row.update(solution_path=str(solution.relative_to(root)),solution_sha256=sha(solution),source_changed=sha(solution)!=sha(original_source))
                save(folder/"row.json",row);save(out/"summary.json",report)
                print(json.dumps(dict(phase="generated",count=report["responses"],subject=subject["id"],label=label,elapsed_s=row["request_elapsed_s"])),flush=True)
        save(out/"generation_complete.json",dict(rows=report["rows"],grading_started=False))
        for row in report["rows"]:
            solution=root/row["solution_path"]
            row["probe"]=probe(solution,out/"generated_probes"/row["subject"]/row["label"])
            if not row["source_changed"]:
                row["official"]=report["originals"][row["subject"]]["official"];row["official_original_reused_identical_bytes"]=True
            else:row["official"]=grade(solution,out/"official_generated"/row["subject"]/row["label"])
            save(out/"summary.json",report)
            print(json.dumps(dict(phase="graded",subject=row["subject"],label=row["label"],probe=row["probe"]["status"],official_level=row["official"]["level"])),flush=True)
        report["complete"]=True;report["verified"]=report["attempts"]==report["responses"]==spec["model_call_budget"]
    except BaseException as e:report["error"]=type(e).__name__+": "+str(e)
    finally:
        report["elapsed_s"]=time.monotonic()-started
        report["assets_unchanged"]=sha(root/"RUN_SPEC.json")==spec_hash and all(sha(root/f)==h for f,h in spec["source_hashes"].items()) and all(sha(deps/f)==h for f,h in spec["dependency_hashes"].items())
        report["verified"]=bool(report["verified"] and report["assets_unchanged"])
        report["arms"]={}
        for arm in ("A","B","C"):
            rows=[x for x in report["rows"] if x["label"].startswith(arm)]
            report["arms"][arm]=dict(rows=len(rows),graded=sum("official" in x for x in rows),repairs=sum(x["role"]=="development_error" and x.get("official",{}).get("level")==3 for x in rows),guard_regressions=sum(x["role"]=="correct_guard" and "official" in x and x["official"]["level"]<3 for x in rows),request_elapsed_s=sum(x.get("request_elapsed_s",0) for x in rows))
        save(out/"summary.json",report)
    print(json.dumps({k:report.get(k) for k in ("complete","verified","attempts","responses","arms","error")}),flush=True)
    return 0 if report["verified"] else 1


if __name__=="__main__":raise SystemExit(main())
