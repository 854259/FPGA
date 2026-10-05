"""Real worker, fake model/native tools; proves fresh calls and boundaries only."""
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import worker


def material(width=8,rising=False):
    ports=f'I would like you to implement a module named TopModule with the following interface. All input and output ports are one bit unless otherwise specified.\n - input clk\n - input in ({width} bits)\n - output pulse ({width} bits)\n'
    body=(f'The module should examine each bit in an {width}-bit vector and detect when the input signal changes from 0 in one clock cycle to 1 the next (similar to positive edge detection). The output bit should be set the cycle after a 0 to 1 transition occurs.' if rising else f'Implement a module that for each bit in an {width}-bit input vector, detect when the input signal changes from one clock cycle to the next (detect any edge). The output bit of pulse should be set to 1 the cycle after the input bit has 0 to 1 or 1 to 0 transition occurs. Assume all sequential logic is triggered on the positive edge of the clock.')
    return ports+body

def trace_log(c,bad):
    row=next(o for o in c['observations'] if o['expected'])
    lines=[]
    for x in c['observations']:
        observed=0 if bad and x==row else x['expected']
        lines.append(f"EDGE_TRACE step={x['step']} phase={x['phase']} expected={x['expected']:x} observed={observed:x}\n")
    if bad:lines.append(f"EDGE_FIRST step={row['step']} phase={row['phase']} expected={row['expected']:x} observed=0\n")
    lines.append(f"R2_PROBE_RESULT task=fixture checks={c['checks']} mismatches={int(bad)}\n")
    return ''.join(lines)

HERE=Path(__file__).resolve().parent


class EdgeIntegration(unittest.TestCase):
    def run_case(self,arm='C',wrong=False,persistent=False,compile_failure=False,unsupported=False,shift=False,edge=False,width=8,rising=False,patch_declaration=False):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);shutil.copytree(HERE/'package',root/'package');shutil.copy2(HERE/'APPENDIX.txt',root/'APPENDIX.txt')
            source=root/'bench/tasks_veval/case';source.mkdir(parents=True)
            fixture='shift.txt' if shift else 'priority.txt'
            text=(HERE/'raw_evidence/test_fixtures'/fixture).read_text(encoding='utf-8')
            if edge:text=material(width, rising)
            if unsupported:text+='\nOutput is delayed by a clock cycle.'
            (source/'prompt.txt').write_text(text,encoding='utf-8')
            (source/'reference.sv').write_text('PRIVATE_REFERENCE_SENTINEL')
            self.assertFalse((source/'initial_response.json').exists())
            code='module TopModule(input [3:0] in,output [1:0] pos);assign pos=0;endmodule'
            if edge:
                code=f'module TopModule(input clk,input [{width-1}:0] in,output '+('' if patch_declaration else 'reg ')+f'[{width-1}:0] pulse);reg [{width-1}:0] prev;always @(posedge clk) begin prev<=in;pulse<=in '+('& ~prev' if rising else '^ prev')+';end endmodule'
            payload=dict(choices=[dict(finish_reason='stop',message=dict(content=code))])
            (root/'RUN_SPEC.json').write_text(json.dumps(dict(model='fake',identity='fake',dependencies_cloud=str(root))))
            tool=root/'tools';tool.mkdir()
            for name in ['xvlog','xvlog.bat']:(tool/name).write_text('fake')
            calls,probes,compiles,events=[],[],[],[]
            def transport(request,*args,**kwargs):
                body=json.loads(request.data);calls.append(body)
                self.assertNotIn('PRIVATE_REFERENCE_SENTINEL',json.dumps(body))
                self.assertNotIn('R2Probe',json.dumps(body));self.assertNotIn('R2_PROBE_RESULT',json.dumps(body))
                if len(calls)==1:self.assertEqual(body['messages'][1],dict(role='user',content=text))
                return io.BytesIO(json.dumps(payload).encode())
            def native(argv,cwd,log,seconds):
                compiles.append(argv);bad=(compile_failure or patch_declaration) and len(compiles)==1
                log.write_text(('ERROR: [VRFC 10-1280] procedural assignment to a non-register pulse' if patch_declaration else 'ERROR: fake syntax') if bad else '')
                return dict(returncode=1 if bad else 0,timeout=False,launch_error=None,remaining_live_group=[])
            def oracle(test,source,out):
                tb=root/test['tb'];self.assertEqual(tb.parent.parent/test['task']/'tb.sv',tb)
                out.mkdir(parents=True);probes.append(test);c=worker.edge_dispatch.parse(text)
                bad=wrong and (persistent or len(probes)==1)
                if edge:
                    row=next(o for o in c['observations'] if o['expected'])
                    log=trace_log(c,bad)
                elif shift:
                    row=next(o for o in c['observations'] if o['expected'])
                    log=f"SHIFT_FIRST step={row['step']} phase={row['phase']} expected={row['expected']:x} observed=0\n" if bad else ''
                else:log='PRIORITY_FIRST value=3 expected=0 observed=1\n' if bad else ''
                (out/'xsim.log').write_text(log)
                return dict(status='fail' if bad else 'pass',checks=c['checks'],mismatches=1 if bad else 0,failure_kind='semantic_mismatch' if bad else None)
            paired=types.SimpleNamespace(check_resource=lambda *args:None,model_idle=lambda *args:None,owned_command=native,oracle=oracle)
            activity=types.SimpleNamespace(append=lambda *args:events.append(args))
            args=types.SimpleNamespace(out=root/'results/case',task='case',arm=arm,kit=root,resource_check=root/'resource.json')
            with patch.object(worker,'ROOT',root),patch('urllib.request.urlopen',side_effect=transport),patch.dict(sys.modules,activity=activity),patch.dict(os.environ,MODEL_NAME='fake',VIVADO_BIN=str(tool),RTL_REPAIRS='1',RTL_MAX_TOKENS='8192',RTL_TEMPERATURE='0'):
                worker.run_worker(args,paired)
            journal=json.loads((args.out/'requests.json').read_text())
            self.assertTrue(all(not x['replayed'] and x['response_received'] for x in journal))
            self.assertEqual(len(events),2*len(calls))
            for i in range(len(compiles)):
                evidence=args.out/'compile_receipts'/str(i)
                self.assertEqual((evidence/'source_before.sv').read_bytes(),(evidence/'source_after.sv').read_bytes())
            row=json.loads((args.out/'worker_result.json').read_text())
            self.assertEqual(row['actual_model_requests'],len(calls))
            self.assertGreater(len(compiles),0,'Compiler fixture must actually be found')
            return calls,probes

    def test_both_arms_share_original_phaseP_edge_and_only_system_suffix_differs(self):
        control=self.run_case('C',edge=True,wrong=True)
        candidate=self.run_case('P',edge=True,wrong=True)
        self.assertEqual(control[0][0]['messages'][1],candidate[0][0]['messages'][1])
        self.assertEqual(candidate[0][0]['messages'][0]['content'],control[0][0]['messages'][0]['content']+worker.semantic_policy.appendix())
        self.assertEqual((len(control[0]),len(control[1])),(2,2))
        self.assertEqual((len(candidate[0]),len(candidate[1])),(2,2))
        self.assertIn('supplied vector edge-detection',candidate[0][1]['messages'][1]['content'])
        self.assertIn('Previous candidate:',candidate[0][1]['messages'][1]['content'])
        repair=worker.load('repair_runtime',HERE/'package/agent/map_runtime.py').skill_texts()[1]
        self.assertEqual(control[0][0]['messages'][0]['content']+worker.semantic_policy.appendix()+'\n'+repair,candidate[0][1]['messages'][0]['content'])

    def test_correct_edge_no_additional_model_call(self):
        for width in [8,17,64]:
            for rising in [False,True]:
                calls,probes=self.run_case('P',edge=True,width=width,rising=rising)
                self.assertEqual((len(calls),len(probes)),(1,1))

    def test_persistent_edge_failure_never_third_request(self):
        calls,probes=self.run_case('P',edge=True,wrong=True,persistent=True)
        self.assertEqual((len(calls),len(probes)),(2,2))

    def test_omitted_polarity_feedback_is_preserved(self):
        calls,probes=self.run_case('P',edge=True,rising=True,wrong=True)
        self.assertIn('No clock-edge polarity omitted',calls[1]['messages'][1]['content'])
        self.assertIn('No reset value or initial history',calls[1]['messages'][1]['content'])

    def test_unknown_edge_semantics_abstains(self):
        calls,probes=self.run_case('P',edge=True,unsupported=True,wrong=True)
        self.assertEqual((len(calls),len(probes)),(1,0))

    def test_original_successful_declaration_patch_returns_unchanged(self):
        calls,probes=self.run_case('P',edge=True,patch_declaration=True)
        self.assertEqual((len(calls),len(probes)),(1,0))

    def test_original_compiler_failure_uses_original_repair(self):
        calls,probes=self.run_case('P',edge=True,compile_failure=True)
        self.assertEqual((len(calls),len(probes)),(2,1))
        self.assertIn('ERROR: fake syntax',calls[1]['messages'][1]['content'])

    def test_original_priority_and_shift_requests_identical_to_C(self):
        for shift in [False,True]:
            for wrong in [False,True]:
                control=self.run_case('C',shift=shift,wrong=wrong)
                candidate=self.run_case('P',shift=shift,wrong=wrong)
                self.assertEqual(control[1],candidate[1])
                self.assertEqual(len(control[0]),len(candidate[0]))
                for c,p in zip(control[0],candidate[0]):
                    self.assertEqual(c['messages'][1],p['messages'][1])
                    base=c['messages'][0]['content'];repair=worker.load('bit_repair_fixture',HERE/'package/agent/map_runtime.py').skill_texts()[1]
                    expected=base[:-len('\n'+repair)]+worker.semantic_policy.appendix()+'\n'+repair if len(control[0])==2 and c is control[0][1] else base+worker.semantic_policy.appendix()
                    self.assertEqual(p['messages'][0]['content'],expected)


if __name__=='__main__':unittest.main()
