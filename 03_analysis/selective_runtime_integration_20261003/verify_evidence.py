"""Verify frozen local artifacts and independent received-request evidence."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


manifest = json.loads((HERE/'source_manifest.json').read_text(encoding='utf-8'))
for name, record in manifest['files'].items():
    data = (ROOT/name).read_bytes()
    assert len(data) == record['bytes'] and sha(data) == record['sha256'], name
summary = json.loads((HERE/'validation_summary.json').read_text(encoding='utf-8'))
raw = (HERE/'local_receipts.json').read_bytes()
assert sha(raw) == summary['receipt_sha256']
rows = json.loads(raw)
assert len(rows) == summary['cases']
assert sum(r.get('requests_received',0) for r in rows) == summary['fake_service_POST_requests']
assert len({r['test'] for r in rows}) == summary['tests']
checked = 0
for row in rows:
    starts = [e for e in row.get('events',[]) if e['tool']=='review_llm_start']
    if starts and row.get('requests') and len(row['requests']) > 1:
        assert sha(json.dumps(row['requests'][-1]).encode()) == starts[-1]['request_sha256'], row['test']
        checked += 1
    assert 'PRIVATE_INPUT_BOUNDARY_CANARY' not in json.dumps(row.get('requests',[])), row['test']
assert checked == summary['received_optional_request_hash_checks']
for name, record in summary['package_files'].items():
    data = (HERE/'package'/name).read_bytes()
    assert sha(data) == record['sha256'], name
    if record['identical_to_original']:
        assert data == (ROOT/record['copied_from']).read_bytes(), name
assert summary['real_Vivado_calls'] == summary['paid_or_shared_model_requests'] == 0
assert not summary['cloud_access']
print(json.dumps({'verified_files':len(manifest['files']), 'case_receipts':len(rows),
                  'request_hash_checks':checked, 'real_model_calls':0,
                  'functional_improvement':'unverified'}, indent=2))
