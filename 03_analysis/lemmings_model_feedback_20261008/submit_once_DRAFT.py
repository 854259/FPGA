"""AMD-only native-only Lemmings admission draft for an existing frozen root.

Never retry this script after an ambiguous response: inspect the existing ticket
whose cwd is the exact root. This script creates no model call itself.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_bytes())
PLAN_SHA = 'a0dad67a4d6b189d5990d59d0a1ed4d2d55f72fd472c5e3c5b57ab6de2ea1c18'
def save(p, j):
    with Path(p).open('x', encoding='utf-8') as f:
        json.dump(j, f, indent=2)
        f.write('\n')


def submit(args):
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    assert sha(args.plan) == PLAN_SHA, 'Admission plan differs from reviewed bytes'
    plan = read(args.plan)
    root = Path(plan['cloud_root'])
    assert str(root) == '/workspace/team/runs/fpga_owner/lemmings_feedback_controls_20261008_v1'
    assert root.is_dir() and root.resolve() == root and not root.is_symlink()
    assert not Path(__file__).resolve().is_relative_to(root)
    assert not args.plan.resolve().is_relative_to(root)
    assert plan['status'] == 'ACTUAL_PURE_INTAKE_PASSED_NATIVE_NOT_SUBMITTED'
    assert args.reviewed_manifest == plan['manifest_sha256'] == sha(root/'SOURCE_MANIFEST.json')
    assert sha(root/'RUN_SPEC.json') == plan['run_spec_sha256']
    sources = read(root/'SOURCE_MANIFEST.json')
    assert len(sources) == plan['source_count'] == 70
    for rel, digest in sources.items():
        assert not Path(rel).is_absolute() and '..' not in Path(rel).parts
        assert not (root/rel).is_symlink()
        target = (root/rel).resolve()
        target.relative_to(root)
        assert sha(target) == digest, rel
    spec = read(root/'RUN_SPEC.json')
    assert spec['schema'] == 'lemmings_feedback_qualification_v1' and spec['qualification_only'] is True
    assert plan['budgets'] == dict(real_model_max=0, native_cases=23, native_eda_max=69,
        native_tool_cap_s=60, stage_cap_s=4500, guard_cap_s=4600, slot_minutes=80)
    assert spec['cloud_root'] == str(root)
    assert (spec['real_model_max'], spec['native_cases'], spec['native_eda_max'],
            spec['native_stage_cap_s'], spec['native_guard_cap_s'], spec['native_slot_minutes']) == (0,23,69,4500,4600,80)
    assert sources == dict(spec['source_hashes'], **{'RUN_SPEC.json': plan['run_spec_sha256']})
    assert sources['native_stage.py'] == plan['native_stage_sha256'] == '61ad3a8056deb2666ad4298f606a7016b8c6bd43097fe6e8daa7593d69b2f892'
    assert sources['guard_wrapper.py'] == plan['guard_sha256'] == 'fdd22d547cab6884b071044a7a1f26f847d8937618a55a201838ff10f77ff9d9'
    receipts = {}
    for rel, digest in plan['qualification_receipts'].items():
        path = root/rel
        assert not path.is_symlink() and path.resolve().is_relative_to(root)
        assert sha(path) == digest
        receipts[rel] = read(path)
    execution = receipts['PURE_EXECUTION_RECEIPT.json']
    combined = receipts['pure_intake/PURE_FLOW_INTAKE_RESULT.json']
    pure = receipts['pure_intake/pure_flow/PURE_FLOW_RESULT.json']
    intake = receipts['pure_intake/intake/INTAKE_RESULT.json']
    assert execution['passed'] and execution['protected_held'] and execution['sources_held']
    assert execution['source_manifest_sha256'] == args.reviewed_manifest
    assert execution['result_sha256'] == plan['qualification_receipts']['pure_intake/PURE_FLOW_INTAKE_RESULT.json']
    assert combined['complete'] and combined['passed'] and combined['error'] is None and combined['source_error'] is None
    assert combined['reports'] == {'pure_flow': pure, 'intake': intake}
    assert combined['source_manifest_sha256'] == pure['source_manifest_sha256'] == args.reviewed_manifest
    assert combined['real_model_calls'] == combined['real_eda_commands'] == 0
    assert pure['complete'] and pure['passed'] and pure['error'] is None
    assert pure['real_model_calls'] == pure['real_eda_commands'] == 0
    assert pure['reports']['pure']['passed'] and pure['reports']['pure']['tests'] == 7
    flow = pure['reports']['flow']
    assert flow['complete'] and flow['passed'] and flow['simulated'] and len(flow['reports']) == 3
    assert flow['actual_model_calls'] == flow['actual_eda_calls'] == 0 and flow['simulated_http_calls'] == 4
    assert intake['complete'] and intake['tasks'] == len(intake['rows']) == 156
    assert intake['model_calls'] == intake['eda_calls'] == 0 and intake['score_inputs_read'] is False
    eligible = [row['task'] for row in intake['rows'] if row['eligible']]
    assert len(eligible) == intake['applicable'] > 0
    assert eligible == intake['eligible_tasks'] == combined['eligible_tasks'] == plan['eligible_tasks']
    assert shutil.disk_usage(root).free >= 2 * 1024**3
    assert args.last_read_comment_id >= plan['last_read_comment_id']
    assert 0 <= time.time()-args.coordination_observed_epoch < 120
    fifo = Path('/workspace/team/tools/task-fifo-20261004/task_fifo.py')
    assert sha(fifo) == '4f1714fdd3ffd092a526e29860bdccf718249ced65e9dbb35947c0ecf8885f3f'
    ticket_dir = Path('/workspace/team/task_fifo/tickets')
    for p in ticket_dir.glob('*.json'):
        assert read(p).get('cwd') != str(root), 'existing same-root ticket: read it, never resubmit'
    for name in ('SUBMISSION_INTENT.json','SUBMISSION.json','native_results','guard','MONITOR_BIRTH.json'):
        assert not (root/name).exists(), 'existing execution evidence: preserve and inspect'
    identity = plan['model_identity']
    assert identity == dict(pid=2013333, starttime='823869819',
        command_sha256='2ef1233963df0e5cc660fc2bed2baa2fca4e30b84d450e79bc9f77381cbd24e1')
    proc = Path('/proc') / str(identity['pid'])
    fields = (proc/'stat').read_text().rsplit(')',1)[1].split()
    assert fields[0] not in ('Z','X') and fields[19] == identity['starttime']
    assert sha(proc/'cmdline') == identity['command_sha256']
    argv = plan['command']
    assert argv[:4] == ['/usr/bin/python3','-B',str(fifo),'submit']
    assert '{resource_check}' in argv and str(root/'guard/status.json') in argv
    assert argv[-len(plan['stage_command']):] == plan['stage_command']
    assert '--pure-flow-result' in plan['stage_command'] and str(root/'native_stage.py') in plan['stage_command']
    intent = dict(at_epoch=time.time(), manifest_sha256=args.reviewed_manifest, admission_plan_sha256=PLAN_SHA,
                  qualification_receipts=plan['qualification_receipts'], argv=argv,
                  last_read_comment_id=args.last_read_comment_id, retries=0,
                  meaning='root-reviewed one-shot FIFO admission, not test success')
    save(root/'SUBMISSION_INTENT.json', intent)
    try:
        cp = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired as error:
        (root/'SUBMIT.stdout').write_bytes(error.stdout or b'')
        (root/'SUBMIT.stderr').write_bytes(error.stderr or b'')
        raise RuntimeError('unknown submission outcome: inspect same cwd/ticket; do not retry') from error
    (root/'SUBMIT.stdout').write_text(cp.stdout)
    (root/'SUBMIT.stderr').write_text(cp.stderr)
    assert cp.returncode == 0, 'failed/unknown submission; read same handle only'
    result = json.loads(cp.stdout)
    result.update(manifest_sha256=args.reviewed_manifest, control_only=True, real_model_max=0,
                  native_eda_max=69, native_cases=23, admission_plan_sha256=PLAN_SHA,
                  pure_flow_reexecution=False, tests_passed=None, retry=False)
    save(root/'SUBMISSION.json', result)
    monitor = Path('/proc') / str(result['monitor_pid'])
    if monitor.is_dir():
        fields = (monitor/'stat').read_text().rsplit(')',1)[1].split()
        save(root/'MONITOR_BIRTH.json', dict(pid=result['monitor_pid'], starttime=fields[19],
                                            state=fields[0], command_sha256=sha(monitor/'cmdline')))
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--reviewed-manifest', required=True)
    parser.add_argument('--last-read-comment-id', type=int, required=True)
    parser.add_argument('--coordination-observed-epoch', type=float, required=True)
    submit(parser.parse_args())
