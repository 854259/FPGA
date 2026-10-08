"""Pure source reconstruction; no production execution, model, EDA or task access."""
import hashlib,json
from pathlib import Path
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def verify(root):
    root=Path(root);up=root/'upstream'
    assert sha(up/'RUN_SPEC.json')=='3fb1531c14b011f80ff58de559e326a4904d3fbdbcf3cdce7d6c955285860ba1'
    original=json.loads((up/'RUN_SPEC.json').read_bytes());assert len(original['source_hashes'])==44
    for n,h in original['source_hashes'].items():assert sha(up/n)==h,n
    copies=json.loads((root/'COPY_PHASE_BASE.json').read_bytes())
    for n,h in copies['copied_hashes'].items():
        if n not in ('baseline_worker.py','package/agent/map_runtime.py'):assert sha(root/n)==h,n
    deltas=json.loads((root/'DECLARATION_SOURCE_DELTAS.json').read_bytes())
    assert set(deltas)=={'baseline_worker.py','package/agent/map_runtime.py'}
    reconstructed={}
    for n,d in deltas.items():
        assert sha(root/n)==d['adapted_sha256']
        lines=(root/n).read_bytes().decode().splitlines(keepends=True)
        for c in reversed(d['changes']):
            assert ''.join(lines[c['adapted_start']:c['adapted_end']])==c['new']
            lines[c['adapted_start']:c['adapted_end']]=c['old'].splitlines(keepends=True)
        data=''.join(lines).encode();assert hashlib.sha256(data).hexdigest()==d['original_sha256']
        expected=(up/('worker.py' if n=='baseline_worker.py' else n)).read_bytes()
        if n=='baseline_worker.py':
            assert expected.count(b"candidate=args.arm == 'P')")==1
            expected=expected.replace(b"candidate=args.arm == 'P')",b'candidate=True)')
        assert data==expected
        reconstructed[n]=hashlib.sha256(data).hexdigest()
    assert sha(root/'package/baseline.py')=='537783e39db22079c33c19af475dbdb760a29ff1656a48c481d434131f84fb51'
    return dict(verified=True,upstream_original_assets=44,reconstructed=reconstructed,
        original_replay_sha256=sha(up/'replay.py'),derived_replay_sha256=sha(root/'declaration_replay.py'),
        official_baseline_unchanged=True,model_calls=0,EDA_calls=0,score_measured=False)
