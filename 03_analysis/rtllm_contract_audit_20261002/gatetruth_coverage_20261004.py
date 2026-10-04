"""AMD-only post hoc source review; no model/EDA, no functional certification."""
import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def header(text):
    clean = re.sub(r'/\*[\s\S]*?\*/|//[^\n]*', '', text)
    return re.sub(r'\s+', '', clean[re.search(r'\bmodule\b', clean).start():].split(';', 1)[0])


def main():
    p = argparse.ArgumentParser()
    for key in ['source', 'notes', 'ledger', 'kit', 'out', 'resource-check']:
        p.add_argument('--' + key, type=Path, required=True)
    a = p.parse_args()
    assert sys.platform == 'linux'
    tick = time.monotonic()
    resource = json.loads(a.resource_check.read_text())
    assert resource['resource_idle'] is True
    assert sha(Path(resource['slot_lock_path'])) == resource['slot_lock_sha256']
    assert sha(a.notes) == '8a6a19e01609f1fe78de594b0c6c9b957dfb90d6fd0d1646c8a563d392c2c6ba'
    assert sha(a.ledger) == '7966d96f633c8f477c8be605685075f07ffbb58b39e84de948b6ae69812e88ab'
    notes = json.loads(a.notes.read_text())['entries']
    previous = {r['task_id']: r for r in json.loads(a.ledger.read_text())['rows']}
    assert len(notes) == len({r['task_id'] for r in notes}) == len(previous) == 60
    repo = Path(__file__).resolve().parents[2]
    rtllm = json.loads((repo / '03_analysis/helper_extraction_20261004/RTLLM_NAME_AUDIT.json').read_text())
    known_rtllm = {r['task'] for r in rtllm['rows']}
    veval = sorted((a.kit / 'bench/tasks_veval').glob('*/prompt.txt'))
    assert len(veval) == 156 and len(known_rtllm) == 44
    known_prompt_hashes = {sha(path) for path in veval}
    rows = []
    for note in notes:
        t = a.source / note['task_id']
        old = previous[note['task_id']]
        assert all(sha(t / rel) == digest for rel, digest in old['source_hashes'].items())
        assert set(note['rtllm_related_names']) <= known_rtllm
        spec = (t / 'spec.md').read_text()
        tb = t / 'tb' / ('test_' + t.name + '.py')
        tree = ast.parse(tb.read_text())
        tests = []
        for n in tree.body:
            if isinstance(n, ast.AsyncFunctionDef) and any(
                    isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and isinstance(d.func.value, ast.Name) and d.func.value.id == 'cocotb'
                    and d.func.attr == 'test' for d in n.decorator_list):
                tests.append(dict(name=n.name, line=n.lineno, end_line=n.end_lineno))
        assert [x['name'] for x in tests] == old['public_test_functions']
        rows.append(dict(**note, source_hashes=old['source_hashes'], public_tests=tests,
            exact_normalized_ansi_header_equal=header((t/'interface.sv').read_text()) == header((t/'ref/ref.sv').read_text()),
            formal_required_upstream=bool(re.search(r'^formal:\s*true', (t/'task.yaml').read_text(), re.M)),
            exact_spec_bytes_match_veval_prompt=sha(t/'spec.md') in known_prompt_hashes,
            existing_control_blockers=old['blockers'], parameter_scope='default only',
            assessment_exposure='Public spec and test bodies reviewed; solver unchanged; not pristine unseen material',
            requirement_section_lines=[i for i,line in enumerate(spec.splitlines(),1)
                if line.startswith('## ') and any(k in line.lower() for k in ('edge','behavior','algorithm','ports'))]))
    a.out.mkdir(parents=True, exist_ok=False)
    private = dict(rows=rows, known_veval_inputs={p.parent.name: sha(p) for p in veval},
                   upstream='2cdaae80ae42c211b049aa521fc2b5db1c2037af', notes_sha256=sha(a.notes))
    target = a.out / 'PRIVATE_REVIEW.json'
    target.write_text(json.dumps(private, indent=2) + '\n')
    public = dict(complete=True, source_commit=(repo/'DELIVERY_COMMIT').read_text().strip(),
        scope='post hoc full-source specification/public-scenario review; not a model experiment',
        tasks_reviewed=len(rows), public_test_functions=sum(len(r['public_tests']) for r in rows),
        public_test_histogram=dict(Counter(len(r['public_tests']) for r in rows)),
        matching_interface_headers=sum(r['exact_normalized_ansi_header_equal'] for r in rows),
        upstream_formal_required_tasks=sum(r['formal_required_upstream'] for r in rows),
        formal_proofs_executed=0, reference_behavior_certified=0,
        known_control_blocked_tasks=sum(bool(r['existing_control_blockers']) for r in rows),
        broad_family_counts=dict(sorted(Counter(r['broad_family'] for r in rows).items())),
        rtllm_broad_related_tasks=sum(bool(r['rtllm_related_names']) for r in rows),
        semantic_duplicates_proven=None, semantic_novelty_proven=False,
        veval_prompts_hashed=len(veval), exact_spec_bytes_match_veval_prompt=sum(r['exact_spec_bytes_match_veval_prompt'] for r in rows),
        family_count_is_effective_sample_size=False, independent_tasks_admitted=0,
        model_calls=0, eda_calls=0, full_experiment_complete=False,
        decision='Do not use original public suite as standalone independent full-quality evidence; retain finite engineering controls',
        private_review_sha256=sha(target), elapsed_s=time.monotonic()-tick)
    (a.out/'summary.json').write_text(json.dumps(public,indent=2)+'\n')
    print(json.dumps(public), flush=True)


if __name__ == '__main__':
    main()
