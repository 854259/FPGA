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

HERE=Path(__file__).resolve().parent


class Fresh(unittest.TestCase):
    def run_case(self,arm='C',wrong=False,persistent=False,compile_failure=False,unsupported=False,shift=False):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);shutil.copytree(HERE/'package',root/'package')
            source=root/'bench/tasks_veval/case';source.mkdir(parents=True)
            fixture='shift.txt' if shift else 'priority.txt'
            text=(HERE/'raw_evidence/test_fixtures'/fixture).read_text(encoding='utf-8')
            if unsupported:text+='\nOutput is delayed by a clock cycle.'
            (source/'prompt.txt').write_text(text,encoding='utf-8')
            (source/'reference.sv').write_text('PRIVATE_REFERENCE_SENTINEL')
            self.assertFalse((source/'initial_response.json').exists())
            code='module TopModule(input [3:0] in,output [1:0] pos);assign pos=0;endmodule'
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
                compiles.append(argv);bad=compile_failure and len(compiles)==1
                log.write_text('ERROR: fake syntax' if bad else '')
                return dict(returncode=1 if bad else 0,timeout=False,launch_error=None,remaining_live_group=[])
            def oracle(test,source,out):
                tb=root/test['tb'];self.assertEqual(tb.parent.parent/test['task']/'tb.sv',tb)
                out.mkdir(parents=True);probes.append(test);c=worker.prompt_map.parse(text)
                bad=wrong and (persistent or len(probes)==1)
                if shift:
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

    def test_A_uses_actual_first_generation_and_no_functional_review(self):
        calls,probes=self.run_case('A',wrong=True);self.assertEqual((len(calls),len(probes)),(1,0))
    def test_C_priority_real_feedback_uses_only_one_original_repair(self):
        calls,probes=self.run_case(wrong=True);self.assertEqual((len(calls),len(probes)),(2,2));self.assertIn('least significant',calls[1]['messages'][1]['content'])
    def test_C_shift_feedback_keeps_stimulus_and_phase(self):
        calls,probes=self.run_case(wrong=True,shift=True);self.assertEqual((len(calls),len(probes)),(2,2));self.assertIn('sequence step',calls[1]['messages'][1]['content']);self.assertIn('clock-edge polarity',calls[1]['messages'][1]['content'])
    def test_correct_draft_has_no_extra_model_call(self):
        calls,probes=self.run_case();self.assertEqual((len(calls),len(probes)),(1,1))
    def test_unknown_prose_abstains(self):
        calls,probes=self.run_case(unsupported=True);self.assertEqual((len(calls),len(probes)),(1,0))
    def test_native_compile_error_keeps_existing_repair(self):
        calls,probes=self.run_case(compile_failure=True);self.assertEqual((len(calls),len(probes)),(2,1));self.assertIn('fake syntax',calls[1]['messages'][1]['content'])
    def test_persistent_mismatch_never_starts_third_call(self):
        calls,probes=self.run_case(wrong=True,persistent=True);self.assertEqual((len(calls),len(probes)),(2,2))


if __name__=='__main__':unittest.main()
