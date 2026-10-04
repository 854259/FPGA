"""Real worker control flow with fake transport/native tools; not RTL evidence."""
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


class Boundary(unittest.TestCase):
    def exercise(self, arm, mismatch=False, compile_failure=False, unsupported=False, persistent=False):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);shutil.copytree(HERE/'package',root/'package')
            inp=root/'raw_evidence/inputs/case';inp.mkdir(parents=True)
            text='The module should implement the Karnaugh map below.\n'
            text+='\n          ab\n   c   | 00 | 01 | 11 | 10 |\n-------+----+----+----+----|\n   0   | 0  | 1  | 0  | 1  |\n   1   | 1  | 0  | 1  | 0  |\n\n'
            text+='module TopModule(input a, input b, input c, output out);'
            # Use a real already-calibrated public prompt to exercise strict parsing.
            text=(HERE/'raw_evidence/inputs/Prob050_kmap1/prompt.txt').read_text()
            if unsupported:text+='\nThe result has a clocked delay.'
            (inp/'prompt.txt').write_text(text,encoding='utf-8')
            (inp/'ref.sv').write_text('PRIVATE_REFERENCE_SENTINEL')
            code='module TopModule(input a,b,c,output out);assign out=a^b^c;endmodule'
            payload=dict(choices=[dict(finish_reason='stop',message=dict(content=code))])
            (inp/'initial_response.json').write_text(json.dumps(payload),encoding='utf-8')
            (root/'RUN_SPEC.json').write_text(json.dumps(dict(model='fake',identity='fake',dependencies_cloud=str(root))))
            tool=root/'tools';tool.mkdir()
            for n in ['xvlog','xvlog.bat']:(tool/n).write_text('fake')
            runtime=worker.load('map_fake_skill',root/'package/agent/runtime.py')
            body=dict(model='fake',messages=[dict(role='system',content=runtime.skill_texts()[0]),dict(role='user',content=text)],temperature=0.0,top_p=1.0,max_tokens=8192)
            (inp/'initial_request.json').write_text(json.dumps(body),encoding='utf-8')
            probes, calls, compiles=[],[],[]
            def transport(request,*args,**kwargs):
                body=json.loads(request.data);calls.append(body)
                data=json.dumps(body)
                self.assertNotIn('PRIVATE_REFERENCE_SENTINEL',data)
                self.assertNotIn('R2Probe',data);self.assertNotIn('R2_PROBE_RESULT',data)
                self.assertIn('Previous candidate:',body['messages'][1]['content'])
                return io.BytesIO(json.dumps(payload).encode())
            def native(argv,cwd,log,seconds):
                compiles.append(argv);log.write_text('ERROR: fake syntax' if compile_failure and len(compiles)==1 else '')
                return dict(returncode=1 if compile_failure and len(compiles)==1 else 0,timeout=False,launch_error=None,remaining_live_group=[])
            def oracle(test,source,out):
                tb=root/test['tb']
                self.assertEqual(tb.parent.parent/test['task']/'tb.sv',tb)
                self.assertTrue(tb.is_file())
                out.mkdir(parents=True);probes.append(test)
                contract=worker.prompt_map.parse(text)
                care=next(c for c in contract['cases'] if c['expected'] is not None)
                bad=mismatch and (persistent or len(probes)==1)
                inputs=','.join(k+'='+str(v) for k,v in care['inputs'].items())
                log=('MAP_FIRST inputs='+inputs+' expected='+str(care['expected'])+' observed='+str(1-care['expected'])+'\n') if bad else ''
                (out/'xsim.log').write_text(log)
                return dict(status='fail' if bad else 'pass',mismatches=1 if bad else 0,failure_kind='semantic_mismatch' if bad else None)
            paired=types.SimpleNamespace(check_resource=lambda *args:None,model_idle=lambda *args:None,owned_command=native,oracle=oracle)
            activity=types.SimpleNamespace(append=lambda *args:None)
            args=types.SimpleNamespace(out=root/'results/case',task='case',arm=arm,resource_check=root/'resource.json',kit=root)
            with patch.object(worker,'ROOT',root),patch('urllib.request.urlopen',side_effect=transport),patch.dict(sys.modules,activity=activity),patch.dict(os.environ,MODEL_NAME='fake',VIVADO_BIN=str(tool),RTL_REPAIRS='1',RTL_MAX_TOKENS='8192',RTL_TEMPERATURE='0'):
                worker.run_worker(args,paired)
            journal=json.loads((args.out/'requests.json').read_text())
            self.assertEqual(journal[0]['replayed'],True)
            self.assertTrue(all(x['response_received'] for x in journal))
            self.assertLessEqual(len(journal),2)
            return calls,probes,json.loads((args.out/'worker_result.json').read_text())

    def test_A_compiled_wrong_keeps_original_no_review(self):
        calls,probes,row=self.exercise('A',mismatch=True)
        self.assertEqual((len(calls),len(probes),row['actual_model_requests']),(0,0,0))

    def test_C_real_counterexample_one_repair(self):
        calls,probes,row=self.exercise('C',mismatch=True)
        self.assertEqual((len(calls),len(probes),row['actual_model_requests']),(1,2,1))
        self.assertIn('simulation disagrees',calls[0]['messages'][1]['content'])

    def test_C_correct_draft_no_review(self):
        calls,probes,row=self.exercise('C')
        self.assertEqual((len(calls),len(probes),row['actual_model_requests']),(0,1,0))

    def test_C_unsupported_keeps_original_flow(self):
        calls,probes,row=self.exercise('C',unsupported=True)
        self.assertEqual((len(calls),len(probes),row['actual_model_requests']),(0,0,0))

    def test_compile_error_consumes_existing_repair(self):
        calls,probes,row=self.exercise('C',compile_failure=True)
        self.assertEqual((len(calls),len(probes),row['actual_model_requests']),(1,1,1))
        self.assertIn('fake syntax',calls[0]['messages'][1]['content'])

    def test_second_failure_does_not_start_third_request(self):
        calls,probes,row=self.exercise('C',mismatch=True,persistent=True)
        self.assertEqual((len(calls),len(probes),row['actual_model_requests']),(1,2,1))


if __name__=='__main__':unittest.main()
