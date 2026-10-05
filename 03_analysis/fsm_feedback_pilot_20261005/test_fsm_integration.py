"""Real worker with fake transport/native results; orchestration, not RTL quality."""
import io,json,os,shutil,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
import worker

HERE=Path(__file__).resolve().parent

def material(partial=False):
    return (HERE/'raw_evidence/test_fixtures'/('partial.txt' if partial else 'full.txt')).read_text(encoding='utf-8')

def point_line(c,row,observed='0'):
    bits=''.join(str(row['inputs'][k]) for k in c['input_names'])
    return f"FSM_FIRST case={row['case']} state={row['state']:x} inputs={bits} expected={row['expected']:x} observed={observed}\n"

class FSMIntegration(unittest.TestCase):
    def run_case(self,arm='F',partial=False,wrong=False,persistent=False,compile_failure=False,
                 unknown=False,patch_declaration=False):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);shutil.copytree(HERE/'package',root/'package')
            source=root/'bench/tasks_veval/case';source.mkdir(parents=True)
            prompt=material(partial)+(' Output must additionally be delayed by one clock cycle.' if unknown else '')
            (source/'prompt.txt').write_text(prompt,encoding='utf-8')
            (source/'reference.sv').write_text('PRIVATE_REFERENCE_SENTINEL')
            # Dummy source never claims semantics; native checks here are explicit fixtures.
            code='module TopModule(input a,output '+('' if patch_declaration else 'reg ')+'b);always @(*) b=a;endmodule'
            payload=dict(choices=[dict(finish_reason='stop',message=dict(content=code))])
            (root/'RUN_SPEC.json').write_text(json.dumps(dict(model='fake',identity='fake',dependencies_cloud=str(root))))
            tools=root/'tools';tools.mkdir()
            for n in ['xvlog','xvlog.bat']:(tools/n).write_text('fake')
            requests,probes,compiles,events=[],[],[],[]
            def transport(req,*a,**kw):
                body=json.loads(req.data);requests.append(body)
                self.assertNotIn('PRIVATE_REFERENCE_SENTINEL',json.dumps(body))
                self.assertNotIn('R2Probe',json.dumps(body));self.assertNotIn('R2_PROBE_RESULT',json.dumps(body))
                if len(requests)==1:self.assertEqual(body['messages'][1],dict(role='user',content=prompt))
                return io.BytesIO(json.dumps(payload).encode())
            def native(argv,cwd,log,seconds):
                compiles.append(argv);bad=(compile_failure or patch_declaration) and len(compiles)==1
                log.write_text(('ERROR: [VRFC 10-1280] procedural assignment to a non-register b' if patch_declaration else 'ERROR: fake syntax') if bad else '')
                return dict(returncode=1 if bad else 0,timeout=False,launch_error=None,remaining_live_group=[])
            def oracle(test,src,out):
                out.mkdir();probes.append(test);c=worker.fsm_dispatch.parse(prompt)
                self.assertEqual(test['checks'],c['checks'])
                self.assertEqual((root/test['tb']).read_text(encoding='utf-8'),worker.fsm_dispatch.render_tb(c,'case'))
                row=next(r for r in c['observations'] if r['expected'])
                bad=wrong and (persistent or len(probes)==1)
                (out/'xsim.log').write_text(point_line(c,row) if bad else '')
                return dict(status='fail' if bad else 'pass',checks=c['checks'],mismatches=1 if bad else 0,
                            failure_kind='semantic_mismatch' if bad else None)
            paired=types.SimpleNamespace(check_resource=lambda *a:None,model_idle=lambda *a:None,
                                         owned_command=native,oracle=oracle)
            args=types.SimpleNamespace(out=root/'results/case',task='case',arm=arm,kit=root,resource_check=root/'resource.json')
            activity=types.SimpleNamespace(append=lambda *a:events.append(a))
            with patch.object(worker,'ROOT',root),patch('urllib.request.urlopen',side_effect=transport),patch.dict(sys.modules,activity=activity),patch.dict(os.environ,MODEL_NAME='fake',VIVADO_BIN=str(tools),RTL_REPAIRS='1',RTL_MAX_TOKENS='8192',RTL_TEMPERATURE='0'):
                worker.run_worker(args,paired)
            journal=json.loads((args.out/'requests.json').read_text())
            self.assertTrue(all(not r['replayed'] and r['response_received'] for r in journal))
            self.assertEqual(len(events),len(requests)*2)
            self.assertGreater(len(compiles),0)
            for i in range(len(compiles)):
                evidence=args.out/'compile_receipts'/str(i)
                self.assertEqual((evidence/'source_before.sv').read_bytes(),(evidence/'source_after.sv').read_bytes())
            return requests,probes

    def test_both_FSM_families_C_abstains_F_repairs_once(self):
        for partial in [False,True]:
            control=self.run_case('C',partial,wrong=True);candidate=self.run_case('F',partial,wrong=True)
            self.assertEqual(control[0][0],candidate[0][0])
            self.assertEqual((len(control[0]),len(control[1])),(1,0))
            self.assertEqual((len(candidate[0]),len(candidate[1])),(2,2))
            self.assertIn('complete combinational state-machine table',candidate[0][1]['messages'][1]['content'])
            self.assertIn('Previous candidate:',candidate[0][1]['messages'][1]['content'])

    def test_correct_fsm_has_no_additional_model_call(self):
        for partial in [False,True]:
            calls,checks=self.run_case(partial=partial)
            self.assertEqual((len(calls),len(checks)),(1,1))

    def test_persistent_failure_keeps_one_repair_budget(self):
        for partial in [False,True]:
            calls,checks=self.run_case(partial=partial,wrong=True,persistent=True)
            self.assertEqual((len(calls),len(checks)),(2,2))

    def test_partial_domain_never_invents_multihot_reset_or_registers(self):
        calls,_=self.run_case(partial=True,wrong=True)
        self.assertIn('Only legal one-hot states',calls[1]['messages'][1]['content'])
        self.assertIn('No state flip-flops, reset signal',calls[1]['messages'][1]['content'])

    def test_full_domain_explicitly_checks_simultaneous_states(self):
        calls,_=self.run_case(wrong=True)
        self.assertIn('explicitly admits simultaneous active states',calls[1]['messages'][1]['content'])

    def test_unknown_semantics_preserves_C_abstention(self):
        calls,checks=self.run_case(unknown=True,wrong=True)
        self.assertEqual((len(calls),len(checks)),(1,0))

    def test_original_successful_declaration_patch_returns_without_new_probe(self):
        calls,checks=self.run_case(patch_declaration=True)
        self.assertEqual((len(calls),len(checks)),(1,0))

    def test_original_compile_failure_feedback_and_budget_preserved(self):
        calls,checks=self.run_case(compile_failure=True)
        self.assertEqual((len(calls),len(checks)),(2,1))
        self.assertIn('ERROR: fake syntax',calls[1]['messages'][1]['content'])

if __name__=='__main__':unittest.main()
