"""Actual owned worker with only FAKE model/native/phase probes; no external IO."""
from pathlib import Path
import io,json,os,shutil,sys,tempfile,types,unittest
from unittest.mock import patch
import worker
from test_policy import failed_stdout

R=Path(__file__).resolve().parent

class Fresh(unittest.TestCase):
    def case(self,arm='P',first_rc=1,abnormal=None,supported=False):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);shutil.copytree(R/'package',root/'package')
            source=root/'bench/tasks_veval/fixture';source.mkdir(parents=True)
            prompt=(R/'raw_evidence/test_fixtures/priority.txt').read_text(encoding='utf-8') if supported else 'Synthetic unknown task; return a fixture module.'
            (source/'prompt.txt').write_text(prompt,encoding='utf-8')
            (source/'reference.sv').write_text('PRIVATE_REFERENCE_SENTINEL')
            (source/'tb.sv').write_text('PRIVATE_TB_SENTINEL')
            worker.save(root/'RUN_SPEC.json',dict(identity='FAKE_DIAGNOSTIC',model='fake',dependencies_cloud=str(root)))
            tools=root/'tools';tools.mkdir()
            for n in ['xvlog','xvlog.bat']:(tools/n).write_text('not executable; FAKE only')
            calls=[];native=[];probes=[];events=[]
            code='module TopModule(input [3:0] in,output [1:0] pos);assign pos=0;endmodule'
            def transport(request,*args,**kwargs):
                self.assertEqual(request.full_url,'http://127.0.0.1:8000/v1/chat/completions')
                body=json.loads(request.data);calls.append(body)
                self.assertNotIn('PRIVATE_REFERENCE_SENTINEL',json.dumps(body));self.assertNotIn('PRIVATE_TB_SENTINEL',json.dumps(body))
                self.assertEqual(body['max_tokens'],8192)
                return io.BytesIO(json.dumps(dict(id=str(len(calls)),choices=[dict(finish_reason='stop',message=dict(content=code))])).encode())
            def command(argv,cwd,log,seconds):
                self.assertIn(Path(argv[0]).name,['xvlog','xvlog.bat']);self.assertEqual(argv[1],'--sv');self.assertEqual(seconds,60)
                native.append(argv);rc=first_rc if len(native)==1 else 0
                text=failed_stdout(str(argv[-1])) if rc!=0 else 'WARNING: fixture success only\n'
                log.write_text(text,encoding='utf-8',newline='\n')
                result=dict(returncode=rc,timeout=False,launch_error=None,remaining_live_group=[],elapsed_s=.001,
                    log_sha256=worker.sha(log),log_bytes=log.stat().st_size)
                if abnormal:result.update(abnormal)
                return result
            def oracle(test,source,out):
                probes.append(test);out.mkdir(parents=True)
                return dict(status='pass',checks=worker.edge_dispatch.parse(prompt)['checks'],mismatches=0,failure_kind=None)
            paired=types.SimpleNamespace(check_resource=lambda *args:None,model_idle=lambda *args:None,owned_command=command,oracle=oracle)
            args=types.SimpleNamespace(out=root/'out',kit=root,task='fixture',arm=arm,resource_check=root/'resource.json')
            activity=types.SimpleNamespace(append=lambda *args:events.append(args))
            with patch.object(worker,'ROOT',root),patch('urllib.request.urlopen',side_effect=transport),patch.dict(sys.modules,activity=activity),patch('subprocess.run',side_effect=AssertionError('unexpected real subprocess')),patch.dict(os.environ,MODEL_NAME='fake',LLM_BASE_URL='http://127.0.0.1:8000/v1',VIVADO_BIN=str(tools),RTL_REPAIRS='1',RTL_MAX_TOKENS='8192',RTL_TEMPERATURE='0'):
                if abnormal:
                    with self.assertRaises(RuntimeError):worker.run_worker(args,paired)
                elif type(first_rc) is not int or first_rc<0:
                    with self.assertRaises(AssertionError):worker.run_worker(args,paired)
                else:worker.run_worker(args,paired)
            self.assertTrue(native);self.assertEqual(len(events),2*len(calls))
            journal=json.loads((args.out/'compile_journal.json').read_bytes())
            for i,e in enumerate(journal):
                p=args.out/'compile_receipts'/str(i)
                self.assertEqual((p/'source_before.sv').read_bytes(),(p/'source_after.sv').read_bytes())
                self.assertEqual(worker.sha(p/'owned_compile.log'),e['log_sha256'])
            if abnormal or type(first_rc) is not int or first_rc<0:
                self.assertEqual(len(calls),1);self.assertFalse((args.out/'worker_result.json').exists())
                return calls,probes,[]
            presentations=[json.loads((args.out/'compile_receipts'/str(i)/'presentation.json').read_bytes()) for i in range(len(journal))]
            self.assertEqual(json.loads((args.out/'worker_result.json').read_bytes())['requests'],len(calls))
            self.assertFalse(list(args.out.glob('elaboration_check_*')))
            return calls,probes,presentations

    def test_P_changes_capped_failed_compile_feedback_then_only_one_repair(self):
        calls,probes,p=self.case();self.assertEqual(len(calls),2);self.assertFalse(probes)
        self.assertIn('LAST_VAR',calls[1]['messages'][1]['content']);self.assertTrue(p[0]['feedback_changed'])
        self.assertTrue(p[0]['priority_invoked']);self.assertFalse(p[1]['priority_invoked'])

    def test_C_preserves_original_fullstdout_and_original_cap(self):
        calls,probes,p=self.case('C');self.assertEqual(len(calls),2)
        self.assertNotIn('LAST_VAR',calls[1]['messages'][1]['content']);self.assertFalse(p[0]['stdout_changed'])

    def test_successful_native_compile_no_sort_no_extra_model_request(self):
        for arm in ['C','P']:
            with self.subTest(arm=arm):
                calls,probes,p=self.case(arm,first_rc=0);self.assertEqual(len(calls),1);self.assertFalse(p[0]['priority_invoked'])

    def test_both_arms_keep_common_latest_phaseP_supported_probe(self):
        for arm in ['C','P']:
            with self.subTest(arm=arm):
                calls,probes,p=self.case(arm,first_rc=0,supported=True)
                self.assertEqual((len(calls),len(probes)),(1,1));self.assertFalse(p[0]['priority_invoked'])

    def test_unknown_signal_boolean_or_supervision_failure_stops_without_repair(self):
        for rc in [None,-9,True]:
            with self.subTest(rc=rc):self.case(first_rc=rc)
        for d in [dict(timeout=True),dict(launch_error='fixture'),dict(remaining_live_group=[dict(pid=123)])]:
            with self.subTest(abnormal=d):self.case(abnormal=d)

if __name__=='__main__':unittest.main()
