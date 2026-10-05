from pathlib import Path
import hashlib,json,zipfile,re
base=Path(__file__).resolve().parents[3];old=base/'03_analysis/edge_feedback_pilot_20261005';root=base/'03_analysis/phase_feedback_pilot_20261005'
assert not (root/'RUN_SPEC.json').exists();root.mkdir(exist_ok=True)
spec=json.loads((old/'RUN_SPEC.json').read_bytes());receipt={}
for n,h in spec['source_hashes'].items():
    source=old/n;assert hashlib.sha256(source.read_bytes()).hexdigest()==h
    if n in ['prepare.py','COPY_RECEIPT.json','UNFROZEN_FAILURES.json']:continue
    target=root/n;target.parent.mkdir(parents=True,exist_ok=True);b=source.read_bytes()
    if source.suffix=='.py':
        text=b.decode();text=re.sub(r"(['\"])E\1",lambda m:m[1]+'P'+m[1],text)
        text=text.replace('edge_feedback_pilot','phase_feedback_pilot').replace('edge_feedback_fresh_C_E','phase_feedback_fresh_C_P')
        b=text.encode()
    target.write_bytes(b);receipt[n]=dict(original_sha256=h,copied_sha256=hashlib.sha256(b).hexdigest())
with zipfile.ZipFile(base/'03_analysis/team_phase_repair_review_20261005/raw_evidence/46_EVIDENCE.zip') as z:
    b=z.read('phase_context.py');assert hashlib.sha256(b).hexdigest()=='90b7c71b480a7cdd9d485e7401509feef996520111e76c03666ac519a2d01afa';(root/'phase_context.py').write_bytes(b)
def modify(name,old,new):
    p=root/name;s=p.read_text(encoding='utf-8');assert s.count(old)==1,(name,old);p.write_bytes(s.replace(old,new).encode())
modify('edge_dispatch.py','import prompt_map','import prompt_map\nimport phase_context')
modify('edge_dispatch.py',"    return edge_contract.render_tb(c, task) if c.get('family') == 'edge' else prompt_map.render_tb(c, task)","    return phase_context.instrument_tb(edge_contract.render_tb(c, task),c) if c.get('family') == 'edge' else prompt_map.render_tb(c, task)")
modify('edge_dispatch.py',"    return edge_contract.counterexample(log, c) if c.get('family') == 'edge' else prompt_map.counterexample(log, c)","    if c.get('family') != 'edge':return prompt_map.counterexample(log,c)\n    rows,bound=phase_context.context(log,c,edge_contract)\n    assert bound is not None\n    return dict(bound['first'],phase_context=bound)")
(root/'phase_feedback.py').write_bytes(b'''"""Bound observed phases only; original non-edge diagnostics unchanged."""
import edge_feedback
import point_feedback
import phase_context
def render(c,result,p):
    if c.get('family')!='edge':return point_feedback.render(c,result,p)
    bound=p['phase_context']
    assert bound['mismatches']==result['mismatches'] and result['checks']==c['checks']
    assert bound['first']=={k:v for k,v in p.items() if k!='phase_context'}
    old=edge_feedback.render(c,result,bound['first'])
    enriched=phase_context.render_feedback(c,bound,edge_feedback)
    assert enriched.startswith(old+' Related observations')
    return enriched
''')
modify('worker.py','import edge_feedback','import edge_feedback\nimport phase_feedback\nimport phase_context\nimport edge_contract')
modify('worker.py','    renderer = edge_feedback if candidate else point_feedback','    renderer = phase_feedback if candidate else point_feedback')
modify('worker.py',"    if result['status'] == 'pass':\n        assert result['mismatches'] == 0", "    if result['status'] == 'pass':\n        if candidate and contract.get('family')=='edge':\n            rows,bound=phase_context.context((folder/'probe/xsim.log').read_text(),contract,edge_contract)\n            assert bound is None\n        assert result['mismatches'] == 0")
modify('audit.py',"candidate_feedback=load('fresh_edge_feedback',run/'edge_feedback.py')","candidate_feedback=load('fresh_phase_feedback',run/'phase_feedback.py')\n        phase_context=load('fresh_phase_observations',run/'phase_context.py');edge_contract=load('fresh_edge_observations',run/'edge_contract.py')")
modify('audit.py',"            if mismatches:\n                point=parser.counterexample(log,c)","            if arm=='P' and c.get('family')=='edge':\n                observed,bound=phase_context.context(log,c,edge_contract)\n                assert (bound is None)==(mismatches==0)\n            if mismatches:\n                point=parser.counterexample(log,c)")
trace='''def trace_log(c,bad):
    row=next(o for o in c['observations'] if o['expected'])
    lines=[]
    for x in c['observations']:
        observed=0 if bad and x==row else x['expected']
        lines.append(f"EDGE_TRACE step={x['step']} phase={x['phase']} expected={x['expected']:x} observed={observed:x}\\n")
    if bad:lines.append(f"EDGE_FIRST step={row['step']} phase={row['phase']} expected={row['expected']:x} observed=0\\n")
    lines.append(f"R2_PROBE_RESULT task=fixture checks={c['checks']} mismatches={int(bad)}\\n")
    return ''.join(lines)

'''
p=root/'test_edge_integration.py';s=p.read_text(encoding='utf-8');s=s.replace("HERE=Path(__file__).resolve().parent",trace+"HERE=Path(__file__).resolve().parent")
s=s.replace('log=f"EDGE_FIRST step={row[\'step\']} phase={row[\'phase\']} expected={row[\'expected\']:x} observed=0\\n" if bad else \'\'','log=trace_log(c,bad)')
assert 'log=trace_log(c,bad)' in s;p.write_bytes(s.encode())
modify('test_replay.py','import edge_feedback','import phase_feedback as edge_feedback')
modify('test_replay.py','from test_edge_integration import material','from test_edge_integration import material,trace_log')
modify('test_replay.py','log=f"EDGE_FIRST step={row[\'step\']} phase={row[\'phase\']} expected={row[\'expected\']:x} observed=0\\n"','log=trace_log(c,True)')
modify('test_boundaries.py','with self.assertRaises(ValueError):','with self.assertRaises((ValueError,AssertionError)):')
for n in ['test_metrics.py']:
    p=root/n;s=p.read_text(encoding='utf-8');s=s.replace('dict(C=.7,E=.9)','dict(C=.7,P=.9)');p.write_bytes(s.encode())
copy=dict(schema='fresh_phase_candidate_copy_v1',source_owner_spec_sha256=hashlib.sha256((old/'RUN_SPEC.json').read_bytes()).hexdigest(),phase_source_sha256=hashlib.sha256((root/'phase_context.py').read_bytes()).hexdigest(),copied_sources=receipt,first_generation_replayed=False,source_peer_review='03_analysis/team_phase_repair_review_20261005/RESULTS.json',factor='C original priority/shift versus P complete prompt-only edge checks with observed phase-group repair feedback. This fresh comparison tests the whole edge-feedback policy, not phase-only causal isolation.',production_deployed=False)
(root/'COPY_RECEIPT.json').write_bytes((json.dumps(copy,ensure_ascii=False,indent=2)+'\n').encode())
print(json.dumps(dict(candidate_sources_written=True,source_files=len(receipt),phase_source_sha256=copy['phase_source_sha256'])))
