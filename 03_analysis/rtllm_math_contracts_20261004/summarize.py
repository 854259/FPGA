"""Recompute contract verification from archived files without EDA/model calls."""
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parent
RAW=ROOT/"raw_evidence"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read(p):
    return json.loads(p.read_text(encoding="utf-8"))


def main():
    archive=read(ROOT/"ARCHIVE.json");assert sha(ROOT/"evidence.zip")==archive["sha256"]
    manifest=read(RAW/"MANIFEST.json")
    for row in manifest["files"]:
        p=(RAW/row["path"]).resolve();assert p.is_relative_to(RAW.resolve())
        assert sha(p)==row["sha256"] and p.stat().st_size==row["bytes"]
    spec=read(ROOT/"RUN_SPEC.json");initial=read(ROOT/"RUN_SPEC.initial.json")
    assert (ROOT/"RUN_SPEC.json").read_bytes()==(RAW/"RUN_SPEC.json").read_bytes()
    assert (ROOT/"RUN_SPEC.initial.json").read_bytes()==(RAW/"RUN_SPEC.initial.json").read_bytes()
    for name,digest in spec["source_hashes"].items():assert sha(ROOT/name)==sha(RAW/name)==digest,name
    assert {n.replace('\\','/'):h for n,h in initial["source_hashes"].items() if n!="prepare.py"}=={n:h for n,h in spec["source_hashes"].items() if n not in ("prepare.py","guard_wrapper.py")}
    failed_archive=read(ROOT/"FAILURE_ARCHIVE.json")
    assert sha(ROOT/"failure_evidence.zip")==failed_archive["sha256"]
    failed=ROOT/"failure_evidence"
    for row in read(failed/"MANIFEST.json")["files"]:
        p=(failed/row["path"]).resolve();assert p.is_relative_to(failed.resolve())
        assert sha(p)==row["sha256"] and p.stat().st_size==row["bytes"]
    assert (failed/"RUN_SPEC.json").read_bytes()==(ROOT/"RUN_SPEC.prior_guard.json").read_bytes()
    old=read(failed/"guard/status.json")
    assert old["complete"] and not old["passed"] and "ProcessLookupError" in old["error"]
    assert old["owned_cleanup"]["verified"] and not old["owned_cleanup"]["remaining"]
    assert old["own_slot_released"] and old["model_unchanged"] and old["protected_files_unchanged"]
    assert read(failed/"results/summary.json")["model_calls"]==0
    assert sha(RAW/"guard_wrapper.py")==spec["resource_guard_sha256"]
    for name,digest in spec["dependency_hashes"].items():assert sha(RAW/"dependency_snapshot"/name)==digest
    failure=read(failed/"launch_failure.json");assert failure["eda_calls"]==failure["model_calls"]==0 and not failure["guard_started"]
    g=read(RAW/"guard/status.json");s=read(RAW/"results/summary.json")
    assert g["complete"] and g["passed"] and g["stage_rc"]==0
    assert g["model_unchanged"] and g["protected_files_unchanged"] and g["own_slot_released"]
    assert g["owned_cleanup"]["verified"] and not g["owned_cleanup"]["remaining"]
    assert s["complete"] and s["verified"] and s["model_calls"]==spec["model_calls"]==0
    assert s["run_spec_sha256"]==sha(ROOT/"RUN_SPEC.json")
    rows=[]
    for contract in spec["contracts"]:
        task=contract["task"];inputs=ROOT/"inputs"/task
        prompt=(inputs/"prompt.txt").read_text(encoding="utf-8")
        assert len(re.findall(r"Module name:",prompt))==1
        assert re.search(r"Module name:\s*TopModule\b",prompt)
        for name in ("positive","negative","agent","baseline"):
            kind="controls" if name in ("positive","negative") else "candidates"
            folder=RAW/"results"/kind/task/name;p=read(folder/"result.json");receipt=read(folder/"adapter_receipt.json")
            assert receipt["inherited_result_sha256"]==sha(folder/"result.json")
            assert receipt["inherited_runner_sha256"]==spec["dependency_hashes"]["probe_runner.py"]
            assert receipt["oracle_adapter_sha256"]==spec["dependency_hashes"]["paired_checkpoint.py"]
            assert all(receipt[k]==v for k,v in p.items()) and s[kind][task][name]==receipt
            assert p["solution_sha256"]==sha(inputs/(name+".sv")) and p["tb_sha256"]==sha(inputs/"tb.sv")
            assert p["inputs_unchanged"] and p["status"]!="environment_error"
            for stage in p["stages"]:
                log=folder/Path(stage["log"]).name
                assert sha(log)==stage["log_sha256"] and log.stat().st_size==stage["log_bytes"]
                assert not stage["remaining_live_group"]
            if name in ("positive","negative"):
                assert p["checks"]==contract["checks"]
                assert p["status"]==("pass" if name=="positive" else "fail")
                if name=="negative":assert p["failure_kind"]=="semantic_mismatch" and p["mismatches"]>0
            if p["checks"] is not None:
                assert p["checks"]==contract["checks"]
                text=(folder/"xsim.log").read_text(encoding="utf-8")
                assert re.findall(r'^R2_PROBE_RESULT task=(\S+) checks=(\d+) mismatches=(\d+)\s*$',text,re.M)==[(task,str(p["checks"]),str(p["mismatches"]))]
            rows.append(dict(task=task,source=name,status=p["status"],failure_kind=p["failure_kind"],checks=p["checks"],mismatches=p["mismatches"],solution_sha256=p["solution_sha256"],tb_sha256=p["tb_sha256"]))
        folder=RAW/"results/synthesis"/task;synth=s["synthesis"][task]
        assert sha(folder/"dut.sv")==sha(inputs/"positive.sv")
        assert sha(folder/"synth.log")==synth["log_sha256"] and not synth["remaining_live_group"] and synth["returncode"]==0
        text=(folder/"synth.log").read_text(encoding="utf-8")
        assert len(re.findall(r'^CONTRACT_SYNTHESIS_PASS\s*$',text,re.M))==1
        assert not re.search(r'^CONTRACT_SYNTHESIS_FAIL\b',text,re.M)
    assert len(rows)==16 and len(s["synthesis"])==4
    candidates=[x for x in rows if x["source"] in ("agent","baseline")]
    result=dict(schema="rtllm_four_math_contracts_audit_v1",status="complete_verified",reliable_contract_tasks=4,
        controls_valid=8,positive_synthesized=4,archived_candidates=8,
        candidate_passes=sum(x["status"]=="pass" for x in candidates),
        candidate_failures=sum(x["status"]=="fail" for x in candidates),rows=rows,
        checks_per_complete_four_task_set=sum(x["checks"] for x in spec["contracts"]),
        elapsed_s=s["elapsed_s"],model_calls=0,new_score=False,formal_runtime_integrated=False,
        guard={k:g[k] for k in ("started_at_utc","finished_at_utc","elapsed_s","stage_rc","model_unchanged","protected_files_unchanged","own_slot_released","model_idle_after")},
        owned_cleanup_verified=True,remaining_owned_processes=0,evidence=dict(archive_sha256=archive["sha256"],manifest_files=len(manifest["files"]),all_hashes_verified=True),
        postflight=read(RAW/"postflight.json"),pre_execution_failure=failure,
        prior_guard_failure=dict(error=old["error"],stage_elapsed_s=read(failed/"results/summary.json")["elapsed_s"],
            archive_sha256=failed_archive["sha256"],manifest_files=len(read(failed/"MANIFEST.json")["files"]),
            owned_cleanup_verified=True,own_slot_released=True,model_calls=0,input_bytes_unchanged=True),
        branch=read(RAW/"launch.json")["git_branch"],coordination=read(RAW/"launch.json")["coordination"],limits=spec["limits"])
    assert result["postflight"]["model_health"]["status"]=="ok" and result["postflight"]["processing_slots"]==0 and not result["postflight"]["slot_exists"]
    (ROOT/"RESULTS.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps({k:result[k] for k in ("status","reliable_contract_tasks","controls_valid","positive_synthesized","candidate_passes","candidate_failures","evidence")}))


if __name__=="__main__":main()
