"""Freeze a new single-factor experiment only after its original-source checks."""
from pathlib import Path
import argparse,datetime,hashlib,json,re,subprocess,sys,zipfile
import factor_proof,preparation_inputs

ROOT=Path(__file__).resolve().parent
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=True,indent=2)+"\n",encoding="utf-8")


def prepare(base_commit):
    assert sys.version_info[:2]==(3,12)
    assert re.fullmatch("[0-9a-f]{40}",base_commit)
    assert not (ROOT/"RUN_SPEC.json").exists(),"Frozen experiment already exists"
    proof=factor_proof.verify(ROOT)
    groups=preparation_inputs.task_groups(ROOT)
    capture_path=ROOT/"raw_evidence/ENVIRONMENT_CAPTURE.json"
    protected_path=ROOT/"raw_evidence/PROTECTED_GROUPS_CAPTURE.json"
    capture=json.loads(capture_path.read_bytes())
    protected=json.loads(protected_path.read_bytes())
    assert capture["model_calls"]==capture["eda_calls"]==0
    assert protected["model_calls"]==protected["eda_calls"]==0
    assert len(protected["groups"])==14 and protected["source_assets"]==565
    import protected_sources
    checked=protected_sources.check(protected,roots={k:v["local_root"] for k,v in protected["groups"].items()})
    assert checked["verified"] and checked["source_assets"]==565
    for name in ["INPUT_MANIFEST.json","guard_wrapper.py","official_eval_guarded.py","collect_evidence.py"]:
        src=ROOT/"upstream"/name;dst=ROOT/name
        if dst.exists():assert dst.read_bytes()==src.read_bytes(),name
        else:dst.write_bytes(src.read_bytes())
    modules=["test_synthesis","test_worker","test_preparation","test_factor_proof","test_metrics","test_audit"]
    x=subprocess.run([sys.executable,"-B","-m","unittest","-v",*modules],cwd=ROOT,capture_output=True,text=True,timeout=60)
    log=dict(returncode=x.returncode,stdout=x.stdout,stderr=x.stderr,python=sys.version,model_calls=0,eda_calls=0)
    save(ROOT/"raw_evidence/PRE_FREEZE_CHECKS_PROCESS.json",log)
    assert x.returncode==0,x.stderr
    count=re.search(r"Ran (\d+) tests",x.stderr);assert count and x.stderr.endswith("OK\n")
    proof=factor_proof.verify(ROOT)
    save(ROOT/"SOURCE_FACTOR_PROOF.json",proof)
    save(ROOT/"LOCAL_CHECKS.json",dict(schema="table_synthesis_local_pure_checks_v1",tests_passed=int(count[1]),**log))
    old=json.loads((ROOT/"upstream/RUN_SPEC.json").read_bytes())
    stable_keys=["kit","model","model_pid","solve_deadline_s","judge_timeout_s",
        "judge_supervisor_timeout_s","max_worker_requests_per_arm","retries",
        "python_major_minor","dependencies_cloud","dependency_hashes","minimum_disk_free_bytes"]
    spec={key:old[key] for key in stable_keys}
    spec.update(schema="table_synthesis_pilot_frozen_v1",identity="prompt_table_synthesis_20261006_v1",
        cloud_root="/workspace/team/runs/fpga_owner/prompt_table_synthesis_20261006_v1",
        base_commit=base_commit,**groups,arms=["C","P"],samples_per_arm_per_task=1,
        max_actual_model_requests=56,stage_timeout_s=7200,slot_minutes=130,solve_deadline_s=300,
        judge_timeout_s=300,judge_supervisor_timeout_s=360,
        max_worker_requests_per_arm=2,retries=0,first_generation_replayed=False,
        frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        original_phase_baseline_spec_sha256=factor_proof.ORIGINAL_SPEC_SHA,
        source_factor_proof_sha256=sha(ROOT/"SOURCE_FACTOR_PROOF.json"),
        environment_capture_sha256=sha(capture_path),protected_groups_capture_sha256=sha(protected_path),
        compiler_tools=capture["compiler_tools"],compiler_env=capture["compiler_env"],udev_files=capture["udev_files"],
        protected=capture["protected"],model_identity=capture["model_identity"],
        protected_group_count=14,protected_source_assets=565,
        minimum_disk_free_bytes=2*1024**3,
        acceptance="Complete28 original-judge samples; at least3 target L1->L3, higher weighted score, no task regression/tool error/deadline/unconfirmed, all7 guards L3 and candidate calls no higher, total P calls<=C. Zero actual requests only on a strictly recomputed P mechanical route. New full156 eligibility only, not adoption.",
        limits=["Deterministic P table emissions are not model generations; actual model calls reported separately.",
            "Nine bounded explicit-combinational prompt templates emit; all other tasks use common original phase-P.",
            "Normal mechanical compile/semantic failures retained and judged, with no second pipeline or resampling.",
            "Known development tasks; no independent, hidden, official-baseline or formal five-sample claim.",
            "Six complete repairs would be at most119/156; first-stage120 goal still needs additional verified gain."])
    # Only actual source and binding files enter the sealed packet. Private drafts
    # and the separate prototype Linux check are outside this execution seal.
    names=[]
    for path in ROOT.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:continue
        name=path.relative_to(ROOT).as_posix()
        if name.startswith("raw_evidence/") and name not in ["raw_evidence/ENVIRONMENT_CAPTURE.json","raw_evidence/PROTECTED_GROUPS_CAPTURE.json"]:continue
        if name.startswith("upstream/raw_evidence/") and name not in ["upstream/"+n for n in old["source_hashes"]]:continue
        if name in ["RUN_SPEC.json","PREPARATION_RECEIPT.json","PREPARATION_ARCHIVE.json","LINUX_PURE_CHECKS.json","LOCAL_CHECKS.json"]:continue
        assert not name.startswith("results/") and not name.startswith("guard/")
        names.append(name)
    names=sorted(names)
    assert all(n in names for n in ["worker.py","baseline_worker.py","synthesis.py","contract.py","audit.py","pilot.py","metrics.py","SOURCE_FACTOR_PROOF.json"])
    spec["source_hashes"]={n:sha(ROOT/n) for n in names}
    save(ROOT/"RUN_SPEC.json",spec)
    receipt=dict(schema="table_synthesis_preparation_v1",spec_sha256=sha(ROOT/"RUN_SPEC.json"),assets=len(names),
        tests_passed=int(count[1]),python=sys.version.split()[0],model_calls=0,eda_calls=0,
        execution_pending=True,quality_gain_measured=False)
    save(ROOT/"PREPARATION_RECEIPT.json",receipt)
    packet=ROOT/"raw_evidence/preparation_v1.zip"
    with zipfile.ZipFile(packet,"x",zipfile.ZIP_DEFLATED) as z:
        for name in names+["RUN_SPEC.json","PREPARATION_RECEIPT.json"]:z.write(ROOT/name,name)
    save(ROOT/"PREPARATION_ARCHIVE.json",dict(spec_sha256=receipt["spec_sha256"],archive_sha256=sha(packet),
        bytes=packet.stat().st_size,files=len(names)+2))
    print(json.dumps(receipt))


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--base-commit",required=True)
    args=parser.parse_args();prepare(args.base_commit)
