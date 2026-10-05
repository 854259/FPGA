"""FAKE archived native traces; checks real source replay without native execution."""
from pathlib import Path
import hashlib,json,tempfile,unittest
import worker,replay,edge_dispatch,phase_feedback,diagnostic_policy
from test_policy import failed_stdout

R=Path(__file__).resolve().parent
baseline=worker.load('diag_fixture_extract',R/'package/baseline.py')
runtime=worker.load('diag_fixture_functions',R/'package/agent/runtime.py')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_bytes())
save=lambda p,v:p.write_text(json.dumps(v),encoding='utf-8')

class Replay(unittest.TestCase):
    def case(self,arm='P',mechanical=False,early=False,tamper=None):
        with tempfile.TemporaryDirectory() as td:
            work=Path(td);prompt='Synthetic unsupported fixture; no task oracle.';contract=edge_dispatch.parse(prompt)
            first_reply='module TopModule(input a, output y);always @* y=a;endmodule'
            second_reply='module TopModule(input a, output y);assign y=a;endmodule'
            first=baseline.extract(first_reply,'rtl');second=baseline.extract(second_reply,'rtl')
            path='/owned/results/worker/work/compile-0/candidate.sv'
            log0=f'ERROR: [VRFC 10-1280] procedural assignment to a non-register y is not permitted [{path}:1]\n' if mechanical else failed_stdout(path)
            selected=diagnostic_policy.feedback(diagnostic_policy.presented(arm,log0,dict(returncode=1,timeout=False,launch_error=None,remaining_live_group=[])))
            patched=runtime.repair_ansi_declarations(first,selected) if mechanical else None
            if mechanical:self.assertTrue(patched)
            records=[(0,first,1,log0)]
            if mechanical:records.append((0,patched,0 if early else 1,'ERROR: [VRFC 10-98] SECOND_COMPILE_ONLY\n'))
            if not early:records.append((1,second,0,''))
            compiles=[]
            for n,(attempt,code,rc,log) in enumerate(records):
                p=work/'compile_receipts'/str(n);p.mkdir(parents=True)
                for name in ['source_before.sv','source_after.sv']:(p/name).write_text(code,encoding='utf-8',newline='\n')
                (p/'owned_compile.log').write_text(log,encoding='utf-8',newline='\n')
                result=dict(returncode=rc,timeout=False,launch_error=None,remaining_live_group=[],elapsed_s=.001,
                    log_sha256=sha(p/'owned_compile.log'),log_bytes=(p/'owned_compile.log').stat().st_size)
                diagnostic_policy.record(arm,result,p/'owned_compile.log',p,save,sha)
                h=sha(p/'source_before.sv')
                compiles.append(dict(argv=['/fake/xvlog','--sv',f'/owned/results/worker/work/compile-{attempt}/candidate.sv'],
                    source_sha256=h,source_before_sha256=h,source_after_sha256=h,**result))
            journal=[]
            for i,reply in enumerate([first_reply] if early else [first_reply,second_reply]):
                p=work/'requests'/str(i);p.mkdir(parents=True)
                feedback='ERROR: [VRFC 10-98] SECOND_COMPILE_ONLY' if tamper=='wrong_mechanical_log' else selected
                user=prompt if i==0 else prompt+'\nPrevious candidate:\n'+first+'\nCandidate diagnostics:\n'+feedback
                if tamper=='repair' and i==1:user+='extra invented advice'
                save(p/'request.json',dict(messages=[dict(role='system',content='FAKE'),dict(role='user',content=user)]))
                save(p/'response.json',dict(id=str(i),choices=[dict(finish_reason='stop',message=dict(content=reply))]))
                journal.append(dict(response_received=True,finish_reason='stop',response_id=str(i)))
            save(work/'requests.json',journal);save(work/'compile_journal.json',compiles)
            trace=[dict(tool='lint',round=0,rc=1,excerpt=selected)]
            if not early:trace.append(dict(tool='lint',round=1,rc=0,excerpt=''))
            (work/'trace.jsonl').write_text('\n'.join(json.dumps(v) for v in trace),encoding='utf-8')
            (work/'solution.v').write_text(patched if early else second,encoding='utf-8',newline='\n')
            target=work/'compile_receipts/0'
            if tamper in ['raw','delivered','feedback','source_before','source_after']:
                names=dict(raw='owned_compile.log',delivered='delivered_stdout.txt',feedback='runtime_feedback.txt',source_before='source_before.sv',source_after='source_after.sv')
                p=target/names[tamper];p.write_bytes(p.read_bytes()+b' ')
            if tamper in ['tool','argv','rc','boolrc','signal']:
                if tamper=='tool':compiles[0]['argv'][0]='/fake/xelab'
                if tamper=='argv':compiles[0]['argv'][-1]='/owned/compile-8/candidate.sv'
                if tamper=='rc':compiles[0]['returncode']=0
                if tamper=='boolrc':compiles[0]['returncode']=True
                if tamper=='signal':compiles[0]['returncode']=-9
                save(work/'compile_journal.json',compiles)
            if tamper=='extra_elaboration':(work/'elaboration_check_0').mkdir()
            def no_probe(*args):raise AssertionError('unsupported fixture cannot call oracle')
            return replay.replay(work,prompt,arm,contract,baseline,runtime,edge_dispatch,phase_feedback,no_probe,sha,read,False)

    def test_exact_P_priority_unique_repair_and_direct_compile_zero_bound(self):
        result=self.case();c=result['native_compile_repair']
        self.assertTrue(c['priority_invoked']);self.assertTrue(c['policy_effect_feedback_changed'])
        self.assertTrue(c['feedback_bound']);self.assertTrue(c['complete']);self.assertTrue(c['repaired_compile_direct'])
        self.assertEqual(c['repaired_compile_returncode'],0);self.assertEqual(result['declaration_patches'],0)

    def test_C_uses_original_first_native_stdout(self):
        result=self.case('C');c=result['native_compile_repair']
        self.assertFalse(c['priority_invoked']);self.assertFalse(c['policy_effect_feedback_changed']);self.assertTrue(c['feedback_bound'])

    def test_raw_feedback_source_tool_argv_rc_or_extra_factor_tamper_rejected(self):
        for mode in ['raw','delivered','feedback','source_before','source_after','tool','argv','rc','boolrc','signal','repair','extra_elaboration']:
            with self.subTest(mode=mode),self.assertRaises(AssertionError):self.case(tamper=mode)

    def test_failed_mechanical_recompile_still_uses_FIRST_feedback(self):
        c=self.case(mechanical=True)['native_compile_repair']
        self.assertTrue(c['feedback_bound']);self.assertEqual(c['mechanical_failed_recompiles'],1)
        with self.assertRaises(AssertionError):self.case(mechanical=True,tamper='wrong_mechanical_log')

    def test_successful_mechanical_early_return_is_not_model_repair_chain(self):
        result=self.case(mechanical=True,early=True)
        self.assertEqual(result['declaration_patches'],1);self.assertIsNone(result['native_compile_repair'])

if __name__=='__main__':unittest.main()
