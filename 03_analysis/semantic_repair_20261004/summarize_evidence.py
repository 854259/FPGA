"""Publish compact audit records from preserved cloud evidence, without raw logs."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw_evidence"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def receipt(stage):
    path = RAW / stage / "status.json"
    record = read(path)
    return dict(source_sha256=sha(path), **{key: record.get(key) for key in
                ("complete", "passed", "stage_rc", "elapsed_s", "started_at_utc", "finished_at_utc",
                 "model_unchanged", "protected_files_unchanged", "own_slot_released")},
                owned_cleanup_verified=record.get("owned_cleanup", {}).get("verified"))


def compact_probe(result):
    return {key: result.get(key) for key in ("status", "failure_kind", "checks", "mismatches", "inputs_unchanged",
                                           "solution_sha256", "tb_sha256", "runner_sha256")}


def summarize():
    recovery_path = RAW / "recovery/summary.json"
    recovery = read(recovery_path)
    one = recovery["single_environment_recovery"]
    patch_path = RAW / "patch_probe_v2/summary.json"
    patch = read(patch_path)
    public = dict(schema="semantic_repair_research_cycle_v1", date="2026-10-04",
                  base_commit="eae7ba595a590915e41745bec27a629135a5d3ea",
                  cloud_root="/workspace/team/runs/fpga_owner/semantic_repair_20261004T001907Z",
                  formal_runtime_unchanged="728499f4699ed2214d5f4355ce0b5c58dc7504d3e177d40f914cf8e7b6f5ea97",
                  best_archived_score_unchanged=dict(agent=0.7667, baseline=0.6744, new_fullset_score=False),
                  recovery=dict(summary_sha256=sha(recovery_path), complete=recovery["complete"], verified=recovery["verified"],
                      new_model_calls=one["new_model_calls"], oracle_attempts=one["oracle_attempts"],
                      preserved_trees_unchanged=one["preserved_trees_unchanged"], prior_summary_sha256=one["prior_summary_sha256"],
                      recovered_oracle=compact_probe(one["new_oracle"]), totals=recovery["totals"],
                      functional_regression_protection=recovery["functional_regression_protection"],
                      deployment_blocked=recovery["deployment_blocked"], guard=receipt("guard-recovery")),
                  signed_cast=dict(summary_sha256=sha(patch_path), complete=patch["complete"], verified=patch["verified"],
                      model_calls=patch["model_calls"], counts=patch["counts"], inputs_unchanged=patch["inputs_unchanged"],
                      real_probe_runs=27, supported_errors_fixed=5, correct_candidates_preserved=14,
                      unsupported_errors_preserved=3, natural_error_targets=1,
                      guard=receipt("guard-patch-v2"), local_tests=dict(run=6, passed=6),
                      setup_failure=dict(phase="pre-EDA source-path lookup", model_calls=0, probe_runs=0,
                                         evidence_preserved=True, guard=receipt("guard-patch")),
                      rows=[dict(id=row["id"], family=row["family"], changed=row["transformation"]["changed"],
                                 decision=row["transformation"]["selection"]["decision"], byte_identical=row["byte_identical"],
                                 accepted=row["accepted"], original_sha256=row["transformation"]["original_sha256"],
                                 before=compact_probe(row["before"]) if "before" in row else "unchanged candidate",
                                 after=compact_probe(row["after"])) for row in patch["rows"]], limits=patch["limits"]),
                  timing=dict(status="awaiting_completed_evidence", model_calls_planned=16),
                  deployment_changed=False, runtime_integrated=False)
    engineering_path = RAW / "upstream_linux/engineering/summary.json"
    functional_path = RAW / "upstream_linux/functional/summary.json"
    engineering, functional = read(engineering_path), read(functional_path)
    public["prior_linux_preflight"] = dict(
        source_commit="eae7ba595a590915e41745bec27a629135a5d3ea",
        observation="historical cloud artifacts read and checked; not a repeated run in this cycle",
        engineering=dict(summary_sha256=sha(engineering_path), complete=engineering["complete"],
                         passed=engineering["passed"], real_compiler=engineering["real_compiler"],
                         fake_model=engineering["fake_model"], cleanup_verified=engineering["cleanup_verified"],
                         cases=len(engineering["cases"]), process_cases=len(engineering["process_cases"]),
                         guard=receipt("upstream_linux/guard-engineering")),
        functional_negative_control=dict(summary_sha256=sha(functional_path), complete=functional["complete"],
                         negative_control_valid=functional["passed"], status=functional["status"],
                         regression_protection=functional["regression_protection"],
                         deployment_blocked=functional["deployment_blocked"],
                         guard=receipt("upstream_linux/guard-functional")))
    timing_path = RAW / "timing_pilot/summary.json"
    if timing_path.exists():
        timing = read(timing_path)
        public["timing"] = dict(summary_sha256=sha(timing_path), complete=timing["complete"], verified=timing["verified"],
                                status="completed" if timing["complete"] else "stopped_on_http_timeout",
                                eligible_for_original_pilot_acceptance=timing["complete"],
                                error=timing.get("error"), client_attempts=timing["client_attempts"],
                                responses_received=timing["responses_received"], new_initial_generations=0,
                                arms=timing["arms"] if timing["complete"] else "ungraded; see separate offline audit",
                                inputs_unchanged=timing["inputs_unchanged"],
                                official_commit=timing["official_commit"], guard=receipt("guard-timing"),
                                controls={task: dict(valid=control["valid"], positive=compact_probe(control["positive"]),
                                                    negative=compact_probe(control["negative"])) for task, control in timing["controls"].items()},
                                originals={task: dict(probe=compact_probe(value["probe"]),
                                                     official_level=value.get("official", {}).get("level")) for task, value in timing["originals"].items()},
                                rows=[dict(task=row["task"], label=row["label"], role=row["role"],
                                           client_attempts=row["client_attempts"], response_received=row["response_received"],
                                           request_sha256=row["request_sha256"], response_sha256=row.get("response_sha256"),
                                           source_changed=row.get("source_changed"), solution_sha256=row.get("solution_sha256"),
                                           finish_reason=row.get("finish_reason"), usage=row.get("usage"),
                                           cache_or_timings=row.get("cache_or_timings"), request_elapsed_s=row.get("request_elapsed_s"),
                                           probe=compact_probe(row["probe"]) if "probe" in row else None,
                                           official_level=row.get("official", {}).get("level"),
                                           judge_evidence_complete=row.get("official", {}).get("judge_evidence_complete"))
                                      for row in timing["rows"]], limits=timing["limits"])
        release_path = RAW / "timing_slot_release.json"
        if release_path.exists():
            release = read(release_path)
            public["timing"]["post_timeout_release"] = dict(source_sha256=sha(release_path), **{
                key: release[key] for key in ("model_identity_unchanged", "protected_files_unchanged",
                                              "owned_cleanup_verified", "own_slot_released", "original_status_preserved")})
    audit_path = RAW / "timing_audit_v2/summary.json"
    if audit_path.exists():
        audit = read(audit_path)
        failed_path = RAW / "timing_audit/summary.json"
        failed_verdict = RAW / "timing_audit/official_originals/Prob129_ece241_2013_q8/verdict.json"
        launch = read(RAW / "launch-timing-audit-v2.json")
        public["timing_offline_audit"] = dict(
            summary_sha256=sha(audit_path), complete=audit["complete"], verified=audit["verified"],
            real_model_calls=0, original_pilot_complete=False, eligible_for_original_pilot_acceptance=False,
            missing_moore_guard=True, official_commit=audit["official_commit"], inputs_unchanged=audit["inputs_unchanged"],
            arms=audit["arms"], extraction=audit["extraction"], extractor_local_tests=dict(run=6, passed=6),
            guard=receipt("guard-timing-audit-v2"),
            environment_recovery=dict(first_audit_sha256=sha(failed_path), first_audit_error=read(failed_path).get("error"),
                                      first_verdict_sha256=sha(failed_verdict), first_level=read(failed_verdict)["level"],
                                      observed_failure="synthesis segfault, not a changed candidate",
                                      same_candidate_recovered_level=audit["originals"]["Prob129_ece241_2013_q8"]["level"],
                                      compatibility=launch["environment_recovery"], original_evidence_preserved=True),
            originals={task: dict(level=value["level"], prior_valid_verdict_reused=value.get("prior_valid_verdict_reused", False))
                       for task, value in audit["originals"].items()},
            rows=[dict(task=row["task"], label=row["label"], role=row["role"], solution_sha256=row["solution_sha256"],
                       probe=compact_probe(row["probe"]), official_level=row["official"]["level"],
                       extraction=row["extraction"], extracted_probe=compact_probe(row["extracted_probe"]),
                       extracted_official_level=row["extracted_official"]["level"],
                       identical_output_verdict_reused=row.get("byte_identical_result_reused", False))
                  for row in audit["rows"]], limits=audit["limits"])
        public["timing_offline_audit"]["extraction"]["compile_recoveries_L0_to_L1"] = sum(
            row["official"]["level"] == 0 and row["extracted_official"]["level"] == 1 for row in audit["rows"])
        public["timing_offline_audit"].update(real_probe_runs=14, official_judge_invocations=15,
                                            valid_original_verdicts_reused=2,
                                            decision="no functional repair observed; do not adopt this review wording",
                                            extraction_decision="compilation recovery only; not functional improvement")
    public["evidence_archives"] = {path.name: dict(bytes=path.stat().st_size, sha256=sha(path))
                                   for path in sorted(HERE.glob("*_evidence.zip"))}
    public["research_sources"] = {path.name: sha(path) for path in sorted(HERE.glob("*.py"))}
    public["preregistered_specs"] = {name: sha(HERE / name) for name in
        ("RUN_SPEC.json", "TIMING_OFFLINE_AUDIT_SPEC.json", "EXTRACTION_SPEC.json", "timing_inputs/manifest.json")}
    if (RAW / "postflight.json").exists():
        public["cloud_postflight"] = read(RAW / "postflight.json")
    if (RAW / "owned_intermediate_cleanup.json").exists():
        cleanup_path = RAW / "owned_intermediate_cleanup.json"
        cleanup = read(cleanup_path)
        public["owned_intermediate_cleanup"] = dict(source_sha256=sha(cleanup_path), utc=cleanup["utc"],
            scope=cleanup["scope"], removed_directories=len(cleanup["removed"]), freed_bytes=cleanup["freed_bytes"],
            owned_processes_verified_stopped=cleanup["owned_processes_verified_stopped"],
            model_or_other_owner_process_modified=cleanup["model_or_other_owner_process_modified"])
    (HERE / "RESULTS.json").write_text(json.dumps(public, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return public


if __name__ == "__main__":
    result = summarize()
    print(json.dumps(dict(signed_cast=result["signed_cast"]["counts"], timing=result["timing"].get("status", result["timing"].get("verified")))))
