"""AMD-only intake and real frozen-table-worker wiring with explicit mocks."""
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import types
import unittest
from unittest.mock import patch
import urllib.request
import zipfile

import baseline_worker as base
import table_feedback as table
import semantic_feedback as factor
import semantic_review as review
import table_worker_original as inherited_worker

assert sys.platform == 'linux' and sys.dont_write_bytecode
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'results';OUT.mkdir(exist_ok=False)
sha=lambda b:hashlib.sha256(b).hexdigest()
manifest=json.loads((ROOT/'SOURCE_MANIFEST.json').read_bytes())
assert all(sha((ROOT/n).read_bytes())==h for n,h in manifest.items())
PROMPT=('Create a module named TopModule with the following interface.\n'
        'All input and output ports are one bit unless otherwise specified.\n'
        ' - input clk\n - input d\n - output q\n'
        'All state updates occur on the positive edge of the clock. '
        'The output is the registered input. The initial output must be zero.')
CODE='module TopModule(input clk, input d, output reg q); always @(posedge clk) q <= d; endmodule\n'
ARCHIVE=Path('/workspace/team/runs/fpga_owner/waveform_first_request_full156_20261007_v1_terminal_review_v2/terminal_v1.zip')
ARCHIVE_SHA='997e65f38eeb1f03fbb20b15fddd8c0f11b4110d28616a5eedfcacbafe6924b1'
assert sha(ARCHIVE.read_bytes())==ARCHIVE_SHA


class Controls(unittest.TestCase):
    def test_first_compile_pass_unverified_review(self):
        x=review.hint(PROMPT,'','skip',True,0)
        self.assertEqual(x['status'],'review_requested')
        self.assertFalse(x['function_verified'] or x['simulated_counterexample'] or x['RTL_generated_or_modified'])
        self.assertIn('explicitly required initial state',x['text'])
        self.assertIn('not a measured counterexample',x['text'])
        self.assertIn('return the same RTL unchanged',x['text'])
        self.assertIn('Do not invent new requirements',x['text'])

    def test_existing_check_compile_failure_and_second_attempt_skip(self):
        for status,compiled,attempt in [('supported',True,0),('skip',False,0),('abstain',True,1)]:
            self.assertEqual(review.hint(PROMPT,'',status,compiled,attempt)['text'],'')

    def test_explicit_scalar_clock_contract_required(self):
        for prompt in (PROMPT.replace('positive edge of the clock','clock tick'),
                       PROMPT.replace(' - input clk',' - input clk (2 bits)'),
                       PROMPT.replace(' - input clk',' - output clk'),
                       PROMPT.replace(' - input clk',' - input clk\n - input clock')):
            self.assertEqual(review.hint(prompt,'','skip',True,0)['text'],'')
        self.assertEqual(review.hint(PROMPT.replace('positive','negative'),'','abstain',True,0)['status'],'review_requested')

    def test_interface_conflicts_do_not_become_errors(self):
        conflict='module TopModule(input [1:0] clk, input d, output q); endmodule'
        self.assertEqual(review.hint(PROMPT,conflict,'skip',True,0)['status'],'skip')

    def test_invalid_budget_and_status_inputs_rejected(self):
        for status,compiled,attempt in [('unknown',True,0),('skip',1,0),('skip',True,2),('skip',True,False)]:
            with self.assertRaises(AssertionError):review.hint(PROMPT,'',status,compiled,attempt)


def forbidden(*args,**kwargs):
    raise RuntimeError('No real inference, EDA, process, socket or shared calls in pure stage')


intake=[];bindings={};table_prompt=None;supported_prompt=None
with zipfile.ZipFile(ARCHIVE) as z:
    names=set(z.namelist())
    prompts=sorted(n for n in names if n.startswith('kit/bench/tasks_veval/') and n.endswith('/prompt.txt'))
    assert len(prompts)==156
    for name in prompts:
        raw=z.read(name);bindings[name]=sha(raw)
        prompt=io.TextIOWrapper(io.BytesIO(raw),encoding='utf-8').read()
        ip=name.rsplit('/',1)[0]+'/interface.txt'
        iface_raw=z.read(ip) if ip in names else b''
        if ip in names:bindings[ip]=sha(iface_raw)
        interface=io.TextIOWrapper(io.BytesIO(iface_raw),encoding='utf-8').read()
        combined=prompt+('\n\nInterface:\n'+interface if interface.strip() else '')
        parsed=table.parse(combined)
        contract=base.edge_dispatch.parse(combined)
        hint=review.hint(prompt,interface,contract['status'],True,0)
        eligible=parsed is None and hint['status']=='review_requested'
        intake.append(dict(task=name.split('/')[-2],prompt_sha256=sha(prompt.encode()),interface_sha256=sha(interface.encode()),
                           table_supported=parsed is not None,original_contract_status=contract['status'],
                           fallback_eligible=eligible,hint=hint))
        if table_prompt is None and parsed is not None:table_prompt=combined
        if supported_prompt is None and parsed is None and contract['status']=='supported' and contract.get('family')!='edge':
            supported_prompt=combined
    assert table_prompt and supported_prompt
    assert all(sha(z.read(n))==h for n,h in bindings.items())

assert table.parse(PROMPT) is None and base.edge_dispatch.parse(PROMPT)['status'] in ('skip','abstain')
log=io.StringIO()
with patch.object(subprocess,'Popen',forbidden),patch.object(subprocess,'run',forbidden),patch.object(socket,'socket',forbidden),patch.object(urllib.request,'urlopen',forbidden):
    test_result=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Controls))
(OUT/'CONTROLS_LOG.txt').write_text(log.getvalue())
assert test_result.wasSuccessful(),log.getvalue()

flows=[]
activity=types.ModuleType('activity')
def flow(label,prompt,arm,compile_rc=0,original_feedback=None,table_mode='pass',original_error=False):
    root=OUT/label;root.mkdir()
    source=root/'source';source.mkdir();(source/'prompt.txt').write_text(prompt)
    out=root/'worker'
    args=types.SimpleNamespace(out=out,arm=arm,task='SyntheticWiringControl',resource_check=root/'mock_resource.json',kit=root/'mock_kit')
    requests=[];compiles=[];oracle_calls=[];events=[]
    activity.append=lambda *a,**k:events.append(dict(mock_only=True,event=a[2]))
    tools=types.SimpleNamespace(check_resource=lambda *a:None,model_idle=lambda *a:None,
                                sha=base.sha,save=base.save)
    def model(request,*a,**k):
        assert len(requests)<2
        requests.append(dict(body=json.loads(request.data),wire_sha256=sha(request.data)))
        response=dict(id='explicit-mock-'+str(len(requests)),choices=[dict(message=dict(content='```verilog\n'+CODE+'```'),finish_reason='stop')],
                      usage=dict(prompt_tokens=0,completion_tokens=0))
        return io.BytesIO(json.dumps(response).encode())
    def compiler(argv,cwd,log,cap):
        assert cap==60 and '--sv' in argv
        compiles.append(dict(source_sha256=base.sha(argv[-1]),mock_only=True))
        Path(log).write_text('ERROR: synthetic control diagnostics\n' if compile_rc else 'INFO: synthetic compile pass\n')
        return dict(returncode=compile_rc,timeout=False,launch_error=None,remaining_live_group=[])
    tools.owned_command=compiler
    def oracle(descriptor,code,out):
        oracle_calls.append(dict(mock_only=True,checks=descriptor['checks']))
        out=Path(out);out.mkdir(parents=True)
        if table_mode=='protocol_fail':
            return dict(inputs_unchanged=False,status='pass',checks=descriptor['checks'],mismatches=0)
        parsed=table.parse(prompt)
        if parsed and table_mode=='mismatch' and len(oracle_calls)==1:
            index,row=next((i,row) for i,row in enumerate(parsed['table']['rows']) if row['care'])
            (out/'xsim.log').write_text('TABLE_FIRST row='+str(index)+' expected='+str(row['expected'])+' observed='+str(1-row['expected'])+'\n')
            return dict(inputs_unchanged=True,status='fail',failure_kind='semantic_mismatch',checks=descriptor['checks'],mismatches=1)
        (out/'xsim.log').write_text('')
        return dict(inputs_unchanged=True,status='pass',checks=descriptor['checks'],mismatches=0)
    tools.oracle=oracle
    first_original=base.functional_feedback
    def custom_original(*a,**k):
        if original_error:raise RuntimeError('synthetic original checker tool failure')
        return original_feedback
    env=dict(PAIRED_TASK_DIR=str(source),MODEL_NAME='explicit-mock-model',RTL_REPAIRS='1',RTL_MAX_TOKENS='8192',RTL_TEMPERATURE='0',LLM_BASE_URL='http://127.0.0.1:8000/v1')
    error=None
    try:
        with (patch.dict(os.environ,env),patch.dict(sys.modules,{'activity':activity}),
              patch.object(subprocess,'Popen',forbidden),patch.object(socket,'socket',forbidden),
              patch.object(urllib.request,'urlopen',model),patch.object(subprocess,'run',forbidden)):
            if original_feedback is not None or original_error:base.functional_feedback=custom_original
            factor.run_worker(base,table,args,tools)
    except RuntimeError as exc:error=str(exc)
    finally:
        assert base.functional_feedback is (custom_original if original_feedback is not None or original_error else first_original)
        base.functional_feedback=first_original
    assert requests and len(requests)<=2
    assert requests[0]['body']['messages'][1]['content']==prompt
    assert all(r['body']['max_tokens']==8192 and r['body']['temperature']==0 and r['body']['top_p']==1 for r in requests)
    receipts={p.stem:json.loads(p.read_text()) for p in (out/'semantic_review_receipts').glob('*.json')}
    binding=factor.bind(base,inherited_worker,out,'A' if arm=='C' else 'P') if error is None else None
    result=dict(label=label,arm=arm,mock_only=True,requests=requests,compiles=compiles,oracle_calls=oracle_calls,
                intercepted_activity_events=events,receipts=receipts,binding=binding,error=error,
                real_model_calls=0,real_eda_calls=0)
    base.save(root/'MOCK_BOUNDARY_RECEIPT.json',result);flows.append(result)
    return result,out


# Freeze only mock configuration; this is not a model-run admission or FIFO ticket.
base.save(ROOT/'RUN_SPEC.json',dict(identity='explicit-mock-semantic-review',model='explicit-mock-model',dependencies_cloud=str(ROOT/'never-used-real-tools')))
os.environ['PATH']='/fake-vivado:'+os.environ.get('PATH','')
# The real runtime resolves the compiler by PATH; the executable is never run.
runtime_load=base.load
def load(name,path):
    module=runtime_load(name,path)
    if str(path).endswith('/map_runtime.py'):module.vivado_tool=lambda name:'/fake/xvlog'
    return module
with patch.object(base,'load',load):
    c,_=flow('unsupported_control',PROMPT,'C')
    p,pout=flow('unsupported_candidate',PROMPT,'P')
    assert len(c['requests'])==1 and len(p['requests'])==2 and not p['oracle_calls']
    assert c['requests'][0]==p['requests'][0]
    assert p['binding']['review_requests']==1 and p['receipts']['1']['status']=='skip'
    prefix=PROMPT+'\nPrevious candidate:\n'+CODE+'\nCandidate diagnostics:\n'
    assert p['requests'][1]['body']['messages'][1]['content']==prefix+p['receipts']['0']['text']
    for mode in ('compile_failure','measured_feedback'):
        kwargs=dict(compile_rc=1) if mode=='compile_failure' else dict(original_feedback='Measured original feedback control')
        a,_=flow(mode+'_control',PROMPT,'C',**kwargs)
        b,_=flow(mode+'_candidate',PROMPT,'P',**kwargs)
        assert len(a['requests'])==len(b['requests'])==2 and a['requests']==b['requests']
        assert not b['receipts']
    a,_=flow('supported_checker_pass',supported_prompt,'P')
    assert len(a['requests'])==1 and a['binding']['review_requests']==0 and len(a['oracle_calls'])==1
    a,_=flow('complete_table_pass',table_prompt,'P')
    assert len(a['requests'])==1 and not a['receipts'] and len(a['oracle_calls'])==1
    a,_=flow('complete_table_mismatch',table_prompt,'P',table_mode='mismatch')
    assert len(a['requests'])==2 and not a['receipts'] and len(a['oracle_calls'])==2
    assert 'complete combinational table' in a['requests'][1]['body']['messages'][1]['content']
    for label,prompt,kwargs in [('table_protocol_failure',table_prompt,dict(table_mode='protocol_fail')),
                                ('original_checker_failure',PROMPT,dict(original_error=True))]:
        a,_=flow(label,prompt,'P',**kwargs)
        assert a['error'] and len(a['requests'])==1 and not a['receipts']
    # Reject source/status/receipt deletion and outer-arm tampering on actual mock evidence.
    original_bytes={n:(pout/n).read_bytes() for n in ['semantic_factor_run.json','semantic_review_receipts/0.json']}
    rejected=0
    for kind in ('arm','status','source_hash','missing_receipt'):
        if kind=='missing_receipt':(pout/'semantic_review_receipts/0.json').unlink()
        else:
            name='semantic_factor_run.json' if kind in ('arm','source_hash') else 'semantic_review_receipts/0.json'
            value=json.loads(original_bytes[name])
            key={'arm':'outer_arm','status':'contract_status','source_hash':'semantic_review_sha256'}[kind]
            value[key]={'arm':'C','status':'supported','source_hash':'0'*64}[kind]
            base.save(pout/name,value)
        try:factor.bind(base,inherited_worker,pout,'P')
        except AssertionError:rejected+=1
        else:raise AssertionError('accepted tampered '+kind)
        finally:
            for n,b in original_bytes.items():(pout/n).write_bytes(b)
    assert rejected==4

assert sha(ARCHIVE.read_bytes())==ARCHIVE_SHA
assert all(sha((ROOT/n).read_bytes())==h for n,h in manifest.items())
base.save(OUT/'PROMPT_INTAKE.json',dict(rows=intake,original_archive_sha256=ARCHIVE_SHA,original_file_hashes=bindings))
eligible=[r['task'] for r in intake if r['fallback_eligible']]
summary=dict(passed=True,tests=test_result.testsRun,full156_prompt_intake=True,eligible=len(eligible),eligible_tasks=eligible,
             inherited_complete_table_worker_exact=True,inherited_frozen_spec_sha256='b499f6c16fa91868ca7ba60a168929204f02d5b0e164f5ade776a65983aa5c5d',
             actual_frozen_worker_mock_flows=len(flows),mock_requests=sum(len(r['requests']) for r in flows),
             mock_compiler_calls=sum(len(r['compiles']) for r in flows),mock_oracle_calls=sum(len(r['oracle_calls']) for r in flows),
             shared_activity_writes=0,first_request_wire_exact=True,compile_failure_and_existing_feedback_wires_exact=True,
             inherited_checker_tool_failures_propagate=True,max2_and_one_remaining_review=True,
             binder_tamper_rejections=rejected,source_hashes_held=True,new_model_calls=0,new_eda_calls=0,new_fifo_tickets=0,
             score_measured=False,model_benefit_and_wall_time_pending=True,adoption=False,
             scope='New eligibility and actual frozen table-worker wiring, using mocked responses/compile/probes only; no new score.')
base.save(OUT/'RESULT.json',summary)
print(json.dumps(summary))
