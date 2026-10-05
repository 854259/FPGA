"""Pure stdout/normal-return controls; every native receipt here is FAKE."""
from pathlib import Path
import hashlib,json,tempfile,unittest
from unittest.mock import patch
import diagnostic_policy as policy
import priority

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v),encoding='utf-8')
def read(p):return json.loads(p.read_bytes())

def failed_stdout(source='/fixture/compile-0/candidate.sv'):
    warnings=['WARNING: [VRFC 10-1] '+str(i)+' '+('fixture-warning-'*27) for i in range(6)]
    repeated=[f'ERROR: [VRFC 10-1280] non-register first_var is not permitted [{source}:{i}]' for i in range(10,21)]
    last=f'ERROR: [VRFC 10-1280] non-register LAST_VAR is not permitted [{source}:40]'
    return '\n'.join(warnings+repeated+[last,'INFO: fixture complete'])+'\n'

def normal(rc=1):return dict(returncode=rc,timeout=False,launch_error=None,remaining_live_group=[])

class Policy(unittest.TestCase):
    def test_only_P_positive_native_return_invokes_original_priority(self):
        text=failed_stdout()
        with patch.object(priority,'prioritize_stdout',wraps=priority.prioritize_stdout) as f:
            self.assertEqual(policy.presented('C',text,normal()),text)
            self.assertEqual(policy.presented('P',text,normal(0)),text)
            self.assertEqual(f.call_count,0)
            actual=policy.presented('P',text,normal())
            self.assertEqual(f.call_count,1);self.assertEqual(actual,priority.prioritize_stdout(text))
            self.assertNotIn('LAST_VAR',policy.feedback(text));self.assertIn('LAST_VAR',policy.feedback(actual))
            self.assertLessEqual(len(policy.feedback(actual)),2048)

    def test_unknown_signal_boolean_timeout_launch_cleanup_rejected(self):
        for arm in ['C','P']:
            for rc in [True,False,None,-9,1.0]:
                with self.subTest(arm=arm,rc=rc),self.assertRaises(AssertionError):policy.presented(arm,'ERROR: fixture',normal(rc))
            for key,value in [('timeout',True),('timeout',0),('launch_error','fixture'),('remaining_live_group',[{'pid':5}]),('remaining_live_group',None)]:
                result=normal();result[key]=value
                with self.subTest(arm=arm,key=key),self.assertRaises(AssertionError):policy.presented(arm,'ERROR: fixture',result)

    def test_raw_native_bytes_are_not_overwritten_including_invalid_UTF8(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);log=p/'owned_compile.log';raw=failed_stdout().encode()+b'\xff';log.write_bytes(raw)
            result=dict(normal(),log_sha256=sha(log),log_bytes=len(raw));before=sha(log)
            delivered=policy.record('P',result,log,p,save,sha)
            original,observed,proof=policy.verify('P',result,p,sha,read)
            self.assertEqual(log.read_bytes(),raw);self.assertEqual(sha(log),before)
            self.assertEqual(observed,delivered);self.assertIn('\ufffd',original)
            self.assertTrue(proof['priority_invoked']);self.assertTrue(proof['feedback_changed'])

    def test_tampered_raw_delivered_feedback_or_proof_rejected(self):
        for member in ['owned_compile.log','delivered_stdout.txt','runtime_feedback.txt','presentation.json']:
            with self.subTest(member=member),tempfile.TemporaryDirectory() as td:
                p=Path(td);log=p/'owned_compile.log';log.write_text(failed_stdout(),encoding='utf-8',newline='\n')
                result=dict(normal(),log_sha256=sha(log),log_bytes=log.stat().st_size)
                policy.record('P',result,log,p,save,sha)
                target=p/member
                if member=='presentation.json':
                    changed=read(target);changed['priority_invoked']=False;save(target,changed)
                else:target.write_bytes(target.read_bytes()+b' ')
                with self.assertRaises(AssertionError):policy.verify('P',result,p,sha,read)

    def test_full_stdout_change_without_capped_feedback_change_is_recorded(self):
        text='INFO: original position\nERROR: [VRFC 10-99] visible single error\n'
        result=policy.proof('P',text,normal())
        self.assertTrue(result['stdout_changed']);self.assertFalse(result['feedback_changed'])

    def test_different_files_codes_variables_and_explicit_scopes_preserved(self):
        messages=[
            'ERROR: [VRFC 10-1] bad x scope A [/own/a.sv:1]',
            'ERROR: [VRFC 10-1] bad x scope A [/own/a.sv:2:8]',
            'ERROR: [VRFC 10-1] bad y scope A [/own/a.sv:1]',
            'ERROR: [VRFC 10-2] bad x scope A [/own/a.sv:1]',
            'ERROR: [VRFC 10-1] bad x scope A [/own/b.sv:1]',
            'ERROR: [VRFC 10-1] bad x scope B [/own/a.sv:1]',
            'ERROR: [VRFC 10-1] bad x scope A at unrelated position 2']
        output=priority.prioritize_stdout('\n'.join(messages))
        self.assertNotIn(messages[1],output)
        for message in messages[:1]+messages[2:]:self.assertIn(message,output)
        self.assertEqual(len(output.splitlines()),6)

    def test_no_severe_preserves_exact_newlines_and_unrecognized_positions(self):
        text='info\r\nWARNING: fixture\r\n'
        self.assertEqual(priority.prioritize_stdout(text),text)
        text='ERROR: bad [/own/file.txt:1]\nERROR: bad [/own/file.txt:2]'
        self.assertEqual(priority.prioritize_stdout(text),text)

    def test_receipt_save_failure_keeps_native_raw_and_propagates(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);log=p/'owned_compile.log';log.write_text('ERROR: fixture',encoding='utf-8')
            result=dict(normal(),log_sha256=sha(log),log_bytes=log.stat().st_size)
            def broken(*args):raise OSError('fixture save failure')
            with self.assertRaises(OSError):policy.record('P',result,log,p,broken,sha)
            self.assertEqual(log.read_text(),'ERROR: fixture');self.assertFalse((p/'presentation.json').exists())

if __name__=='__main__':unittest.main()
