"""AMD-only capacity arithmetic from frozen evidence; never launches a model.

All scenarios are planning alternatives, not a newly authorized or admitted run.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time
import zipfile


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(a):
    assert sys.platform == 'linux'
    expected = {
        'historical': '11aca0da9719de519d503ca307e7a03c39bd6dfa80c1abcc2efc3803f47f1e7e',
        'statistics': '34ff19999901c52ed4996ec932034f4623c12abf4b1a288a75d5d7e06dcbec87',
        'rules': '559d828ce7b167ab78410d773295c90e4e7b679e013cbb430ef097330638fdb2',
        'old_archive': '64ace96d59d9a1802513f20be3e21c191786ba04d2054b9ab4072900893c7616',
        'new_archive': 'ac3b27f553bbf274d2edc875a7a3354b42741a9861ca409b37b779d1c6067055',
        'paired': '78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c'}
    for name, value in expected.items():
        assert sha(getattr(a, name)) == value, name
    imp = importlib.util.spec_from_file_location('capacity_resource', a.paired)
    resource = importlib.util.module_from_spec(imp)
    imp.loader.exec_module(resource)
    resource.check_resource(a.resource_check, a.kit, first=True)
    started = time.monotonic()
    old = json.loads(a.historical.read_text())
    stats = json.loads(a.statistics.read_text())
    assert old['observed']['baseline']['tasks'] == stats['primary']['tasks'] == 156
    assert '每题独立生成 5 次' in a.rules.read_text(encoding='utf-8')
    baseline = old['observed']['baseline']['observed_llm_response_seconds'] + old['judge_seconds']['baseline']
    ac = sum(stats['primary']['solve_seconds'].values()) + sum(stats['primary']['judge_seconds'].values())
    components = ac + baseline
    stage_proxy = stats['reported_stage_wall_seconds'] + baseline
    archive_stats = []
    for p in (a.old_archive, a.new_archive):
        with zipfile.ZipFile(p) as z:
            rows = [e for e in z.infolist() if e.filename.startswith(('run/samples/', 'run/results/samples/')) and not e.is_dir()]
            prefixes = set()
            for row in rows:
                if row.filename.endswith('/row.json'):
                    prefixes.add(row.filename[:-len('/row.json')])
            assert len(prefixes) == 312
            archive_stats.append(dict(archive_sha256=sha(p), completed_outputs=312,
                sample_file_count=len(rows), sample_expanded_bytes=sum(e.file_size for e in rows),
                sample_compressed_payload_bytes=sum(e.compress_size for e in rows),
                sample_cache_files=sum('xsim.dir/' in e.filename for e in rows),
                archive_total_bytes=p.stat().st_size))
    raw_per_output = max(x['sample_expanded_bytes']/312 for x in archive_stats)
    zip_per_output = max(x['sample_compressed_payload_bytes']/312 for x in archive_stats)
    scenarios = []
    for n, note in ((156, 'VerilogEval only: lacks RTLLM and independent validation'),
                    (185, '156 plus 29 RTLLM finite domains: preserve all44 ledger with15 blocked; not full44 qualification'),
                    (200, '156 plus44 nominal tasks: currently15 RTLLM contracts blocked; not executable admission')):
        outputs = n*3*5
        requests = n*5*(2+2+1)
        hours = components/156*5*n/3600
        scenarios.append(dict(tasks=n, note=note, arms=3, samples_per_task=5, outputs=outputs,
            request_cap_assuming_one_repair_per_agent=requests, independent_tasks_included=0,
            mixed_historical_components_hours=hours,
            paired_wall_plus_baseline_components_hours=stage_proxy/156*5*n/3600,
            planning_sensitivity_hours={str(factor):hours*factor for factor in (1.0,1.25,1.5,2.0)},
            sum_of_row_caps_hours=outputs*(300+180)/3600,
            projected_retained_raw_bytes=round(raw_per_output*outputs),
            projected_zip_payload_bytes=round(zip_per_output*outputs),
            projected_raw_plus_two_zip_payloads_bytes=round((raw_per_output+2*zip_per_output)*outputs),
            quota_sufficiency=None, launch_eligible=False))
    assert [r['outputs'] for r in scenarios] == [2340,2775,3000]
    assert [r['request_cap_assuming_one_repair_per_agent'] for r in scenarios] == [3900,4625,5000]
    a.out.mkdir(exist_ok=False)
    result = dict(complete=True, analysis_only=True, source_commit=a.source_commit,
        source_sha256=sha(Path(__file__)), inputs=expected, model_calls=0, eda_calls=0,
        observed_three_arm_component_proxy_seconds=components,
        historical_baseline_is_response_plus_judging_only=True,
        historical_snapshots_are_not_same_run=True,
        archive_observations=archive_stats, scenarios=scenarios,
        current_disk_free_bytes=shutil.disk_usage('/workspace').free,
        quota_status='Unknown: current Edge AMD developer portal is logged out; no credentials requested or login submitted.',
        full_batch_complete=False, budget_frozen=False, job_started=False,
        blockers=['No new candidate qualified for independent validation',
                  'No admitted independent triggering natural tasks',
                  '15 of44 RTLLM contracts unresolved;29 limited to audited finite domains',
                  'Compute credit hours and expiry not available from logged-out console',
                  'Official wall limits/base image and formal32GB delivery remain unverified'],
        storage_limits=['Both archives have zero retained xsim.dir entries: estimates omit transient compiler cache peaks.',
                        'ZIP payload omits ZIP directory headers; immutable sources, models, extra independent tasks and future log growth excluded.',
                        'Current disk headroom cannot certify a complete unattended run; reserve and per-row disk-stop policy must be frozen.'],
        timing_limits=['Mixed historical compute components are estimates, not measured three-arm wall time or a confidence interval.',
                       '1.25/1.5/2 multipliers are sensitivity scenarios, not probabilistic guarantees.',
                       'Row-cap sums omit setup/cleanup/archive overhead and do not authorize that many hours.',
                       'Historical300-second solve and180-second judge caps are development limits, not final official limits.',
                       'Each additional independent task adds15 outputs and at most25 requests under this plan; time/space costs are unknown.'],
        checked_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), elapsed_s=time.monotonic()-started)
    resource.check_resource(a.resource_check, a.kit)
    (a.out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for n in ('historical','statistics','rules','old-archive','new-archive','paired','kit','resource-check','out'):
        p.add_argument('--'+n, type=Path, required=True)
    p.add_argument('--source-commit', required=True)
    main(p.parse_args())
