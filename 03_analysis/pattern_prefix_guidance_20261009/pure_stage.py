"""AMD-only semantic/math, prompt intake and actual original-worker mock wiring."""
import hashlib
import importlib.util
import io
import itertools
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.request
import zipfile
import pattern_guidance as guidance
import pattern_request as factor

assert sys.platform == 'linux' and sys.dont_write_bytecode
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'results';OUT.mkdir(exist_ok=False)
sha=lambda b:hashlib.sha256(b).hexdigest()
manifest=json.loads((ROOT/'SOURCE_MANIFEST.json').read_bytes())
assert all(sha((ROOT/n).read_bytes())==h for n,h in manifest.items())
PREFIX='All input and output ports are one bit unless otherwise specified.\n - input data_pin\n - output ready\n'
PROMPT=PREFIX+'When data_pin has produced the values 1, 0, 1 in three successive clock cycles, the controller then follows the specified output timing.'
def payload(prompt,interface='',repair=False):
    user=prompt+('\n\nInterface:\n'+interface if interface.strip() else '')
    if repair:user+='\nPrevious candidate:\nmodule Candidate; endmodule\nCandidate diagnostics:\nERROR: control'
    return json.dumps(dict(model='mock-model',messages=[dict(role='system',content='original skill'),dict(role='user',content=user)],temperature=0.0,top_p=1.0,max_tokens=8192)).encode()


class Controls(unittest.TestCase):
    def test_explicit_pattern_and_raw_source_anchor(self):
        answer=guidance.extract(PROMPT)
        self.assertEqual(answer['status'],'supported')
        self.assertEqual(answer['pattern'],'101')
        begin,end=answer['source_span']
        self.assertEqual(answer['source_clause_sha256'],sha(PROMPT[begin:end].encode()))
        self.assertTrue(answer['derives_semantic_prefix_transitions'])
        self.assertFalse(answer['emits_rtl'])
        self.assertFalse(answer['determines_reset_enable_output_timing'])

    def test_overlap_counterexample_1101(self):
        rows=guidance.transitions('101');state=0
        for bit in '1101':state=rows[state][bit]
        self.assertEqual(state,'complete')
        self.assertEqual(rows[1]['1'],1)
        self.assertIn('Matched prefix 1: next 0 -> 10; next 1 -> 1.',guidance.extract(PROMPT)['addendum'])

    def test_independent_full_stream_property(self):
        # Expected recognition comes from the full sampled string, not the
        # helper's state construction. All binary patterns2..5, all streams8.
        checks=0
        for length in range(2,6):
            for bits in itertools.product('01',repeat=length):
                pattern=''.join(bits);rows=guidance.transitions(pattern)
                for stream in itertools.product('01',repeat=8):
                    seen='';state=0
                    for bit in stream:
                        seen+=bit;next_state=rows[state][bit]
                        expected=seen.endswith(pattern)
                        self.assertEqual(next_state=='complete',expected,(pattern,seen))
                        checks+=1
                        if expected:break # Post-recognition control is unspecified.
                        self.assertIsInstance(next_state,int);state=next_state
        self.assertGreater(checks,10000)
        self.property_checks=checks

    def test_generic_renaming_and_other_patterns(self):
        other=PROMPT.replace('data_pin','sensor_bit').replace('1, 0, 1','0, 0, 1, 0').replace('three','four')
        answer=guidance.extract(other)
        self.assertEqual((answer['status'],answer['input'],answer['pattern']),('supported','sensor_bit','0010'))

    def test_cycle_count_mismatch_abstains(self):
        self.assertEqual(guidance.extract(PROMPT.replace('three','four'))['status'],'abstain')

    def test_unknown_vector_or_output_input_abstains(self):
        for interface in ('module Unit(input [3:0] data_pin, output ready); endmodule',
                          'module Unit(output data_pin, input ready); endmodule'):
            self.assertEqual(guidance.extract(PROMPT,interface)['status'],'abstain')
        self.assertEqual(guidance.extract(PROMPT.replace(' - input data_pin',' - input data_pin [3:0]'))['status'],'abstain')

    def test_formal_scalar_interface_and_conflict(self):
        interface='module Unit(input logic data_pin, output ready); endmodule'
        self.assertEqual(guidance.extract(PROMPT,interface)['status'],'supported')
        self.assertEqual(guidance.extract(PROMPT,interface.replace('output ready','output data_pin'))['status'],'abstain')

    def test_multiple_nonbinary_and_negative_patterns_abstain(self):
        for text in (PROMPT+' '+PROMPT, PROMPT.replace('1, 0, 1','1, 2, 1'),
                     PROMPT.replace('When data_pin','Never: When data_pin'),
                     PROMPT+' Use non-overlapping matching.',
                     PROMPT+' Restart the partial match after mismatch.'):
            self.assertEqual(guidance.extract(text)['status'],'abstain')

    def test_control_abstain_and_repair_wire_exact(self):
        for prompt,arm,round_index in ((PROMPT,'C',0),(PROMPT,'C',1),(PROMPT,'P',1),('Unknown specification','P',0)):
            raw=payload(prompt,repair=bool(round_index));wire,receipt=factor.transform(raw,prompt,'',arm,round_index)
            self.assertEqual(wire,raw);self.assertFalse(receipt['changed'])

    def test_only_supported_first_user_message_changes(self):
        raw=payload(PROMPT);wire,receipt=factor.transform(raw,PROMPT,'','P',0)
        before=json.loads(raw);after=json.loads(wire)
        self.assertTrue(receipt['changed']);self.assertTrue(receipt['derives_semantic_prefix_transitions'])
        self.assertEqual(after['messages'][1]['content'],before['messages'][1]['content']+factor.MARKER+guidance.extract(PROMPT)['addendum'])
        after['messages'][1]=before['messages'][1];self.assertEqual(after,before)
        self.assertEqual(receipt['model_request_delta'],0)

    def test_budget_index_or_source_mismatch_rejected(self):
        with self.assertRaises(AssertionError):factor.transform(payload(PROMPT),PROMPT,'','P',2)
        with self.assertRaises(AssertionError):factor.transform(payload(PROMPT),PROMPT+' changed','','P',0)
        body=json.loads(payload(PROMPT));body['max_tokens']=4096
        with self.assertRaises(AssertionError):factor.transform(json.dumps(body).encode(),PROMPT,'','P',0)

    def test_crlf_and_reserved_identifier(self):
        crlf=PROMPT.replace('\n','\r\n')
        self.assertEqual(guidance.extract(crlf)['status'],'supported')
        self.assertEqual(guidance.extract(PROMPT.replace('data_pin','always'))['status'],'abstain')


def forbidden(*args,**kwargs):
    raise RuntimeError('No real model/EDA/subprocess/network in this stage')

original_archive=Path('/workspace/team/runs/fpga_owner/waveform_first_request_full156_20261007_v1_terminal_review_v2/terminal_v1.zip')
original_hash='997e65f38eeb1f03fbb20b15fddd8c0f11b4110d28616a5eedfcacbafe6924b1'
assert sha(original_archive.read_bytes())==original_hash
spec=importlib.util.spec_from_file_location('original_prefix_worker',ROOT/'runtime_original.py')
runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)
bindings={};intake=[];flows=[];stream=io.StringIO()
with patch.object(subprocess,'Popen',forbidden),patch.object(subprocess,'run',forbidden),patch.object(socket,'socket',forbidden),patch.object(urllib.request,'urlopen',forbidden):
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Controls)
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    (OUT/'CONTROLS_LOG.txt').write_text(stream.getvalue())
    assert result.wasSuccessful(),stream.getvalue()
    with zipfile.ZipFile(original_archive) as z:
        def retained(name):
            data=z.read(name);bindings[name]=sha(data);return data
        names=set(z.namelist())
        prompts=sorted(n for n in names if n.startswith('kit/bench/tasks_veval/') and n.endswith('/prompt.txt'))
        assert len(prompts)==156
        for name in prompts:
            prompt=retained(name).decode();iface_name=name.rsplit('/',1)[0]+'/interface.txt'
            interface=retained(iface_name).decode() if iface_name in names else ''
            extraction=guidance.extract(prompt,interface)
            intake.append(dict(task=name.split('/')[-2],prompt_sha256=sha(prompt.encode()),interface_sha256=sha(interface.encode()),
                               extraction=extraction))
        # The real original worker constructs the requests. Replies and compiler
        # outcomes below are explicitly mocked; no functional score is measured.
        base='run/results/samples/C/Prob139_2013_q2bfsm/worker/requests/0/'
        first=json.loads(retained(base+'request.json'));reply=retained(base+'response.json')
        original_prompt=first['messages'][1]['content'];skill=first['messages'][0]['content']
        assert guidance.extract(original_prompt)['status']=='supported'
        for label,prompt,arm in [('control',original_prompt,'C'),('candidate',original_prompt,'P'),('abstain','Unspecified behavior','P')]:
            with tempfile.TemporaryDirectory(dir=OUT) as directory:
                folder=Path(directory);task=folder/'prompt_only';task.mkdir();(task/'prompt.txt').write_text(prompt)
                out=folder/'worker';out.mkdir();context=dict(prompt=prompt,interface='',arm=arm,out=out,receipts=[])
                requests=[];compiles=[]
                def fake_model(request,**kwargs):
                    assert len(requests)<2;requests.append(json.loads(request.data));return io.BytesIO(reply)
                def fake_compile(argv,**kwargs):
                    assert len(compiles)<2 and argv[1]=='--sv'
                    compiles.append(sha(Path(argv[-1]).read_bytes()))
                    return subprocess.CompletedProcess(argv,1,'ERROR: synthetic compiler control')
                env=dict(MODEL_NAME=first['model'],RTL_REPAIRS='1',RTL_MAX_TOKENS='8192',RTL_TEMPERATURE='0',LLM_BASE_URL='http://127.0.0.1:8000/v1')
                previous=Path.cwd()
                try:
                    os.chdir(out)
                    wrapped=factor.request_class(urllib.request.Request,context)
                    with (patch.dict(os.environ,env),patch.object(runtime,'skill_texts',lambda:(skill,'synthetic repair skill')),
                         patch.object(runtime,'vivado_tool',lambda name:'/fake/xvlog'),patch.object(urllib.request,'Request',wrapped),
                         patch.object(urllib.request,'urlopen',fake_model),patch.object(subprocess,'run',fake_compile)):
                        runtime.worker(task,out)
                finally:os.chdir(previous)
                assert len(requests)==len(compiles)==len(context['receipts'])==2
                for index,receipt in enumerate(context['receipts']):
                    receipt_root=out/'pattern_request_receipts'/str(index)
                    raw=(receipt_root/'original_wire.bin').read_bytes();wire=(receipt_root/'forwarded_wire.bin').read_bytes()
                    assert sha(raw)==receipt['original_wire_sha256'] and sha(wire)==receipt['forwarded_wire_sha256']
                    assert requests[index]==json.loads(wire)
                    if arm=='C' or index==1 or label=='abstain':assert raw==wire
                if label=='candidate':assert context['receipts'][0]['changed']
                original_first=json.loads((out/'pattern_request_receipts/0/original_wire.bin').read_bytes())
                if label!='abstain':assert original_first==first
                flow=dict(label=label,requests=requests,compilation_source_hashes=compiles,
                          receipts=context['receipts'],solution_sha256=sha((out/'solution.v').read_bytes()))
                flows.append(flow)
                # Retain mock wire/control evidence outside the temporary worker.
                (OUT/(label+'_MOCK.json')).write_text(json.dumps(flow,ensure_ascii=False,indent=2)+'\n')
        assert flows[0]['requests'][1]==flows[1]['requests'][1]
        assert flows[0]['compilation_source_hashes']==flows[1]['compilation_source_hashes']
        assert flows[0]['solution_sha256']==flows[1]['solution_sha256']
        assert all(sha(z.read(n))==h for n,h in bindings.items())
assert sha(original_archive.read_bytes())==original_hash
assert all(sha((ROOT/n).read_bytes())==h for n,h in manifest.items())
(OUT/'PROMPT_INTAKE.json').write_text(json.dumps(dict(rows=intake,source_archive_sha256=original_hash,retained_hashes=bindings),ensure_ascii=False,indent=2)+'\n')
eligible=[r['task'] for r in intake if r['extraction']['status']=='supported']
summary=dict(passed=True,tests=result.testsRun,all156_prompt_intake=True,eligible_tasks=eligible,eligible=len(eligible),abstained=156-len(eligible),
    actual_original_worker_mock_flows=3,mock_requests=6,mock_compiler_calls=6,
    C_abstain_and_repair_wires_exact=True,only_supported_first_user_append=True,
    reused_request_class_only_receipt_folder_changed=True,
    semantic_transition_derivation_explicit=True,RTL_generated_by_guidance=False,
    original_archive_sha256=original_hash,source_hashes_held=True,
    new_model_calls=0,new_eda_calls=0,new_fifo_tickets=0,score_measured=False,
    original_phase_worker_qualification_pending=True,adoption=False,
    scope='Mathematical prefix semantics, prompt-only intake and actual original-runtime mocked wiring; no new inference or score.')
(OUT/'RESULT.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))
