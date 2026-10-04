"""Fake external commands: verify continuation cannot bypass audit/admission gates."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent


class Continuation(unittest.TestCase):
    def execute(self,mode):
        sp=importlib.util.spec_from_file_location('continuation_check',HERE/'postflight_then_pilot.py')
        c=importlib.util.module_from_spec(sp);sp.loader.exec_module(c)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);post=root/'post';run=root/'run';pilot=root/'pilot'
            for p in (post,run,pilot):p.mkdir()
            for folder in (post,pilot):
                for name in ('audit.py','collect_evidence.py'):(folder/name).write_text('fake command only\n')
            c.save(run/'RUN_SPEC.json',{})
            c.save(pilot/'RUN_SPEC.json',dict(source_hashes={}))
            c.save(pilot/'PREPARATION_RECEIPT.json',dict(postflight_hashes={n:c.sha(pilot/n) for n in ('audit.py','collect_evidence.py')}))
            c.save(run/'queue_status.json',dict(complete=True,state='stopped_with_evidence' if mode=='full_failed' else 'complete',completed_samples=312))
            if mode=='stop':(post/'STOP_AUTONOMOUS').write_text('stop')
            commands=[];events=[]
            def fake_command(argv,**kwargs):
                commands.append(argv)
                if '--archive' in argv and '--run-root' in argv:
                    Path(argv[argv.index('--archive')+1]).write_bytes(b'fake archive')
                elif '--out' in argv:
                    if mode=='audit_failed':raise subprocess.CalledProcessError(1,argv)
                    out=Path(argv[argv.index('--out')+1]);out.mkdir()
                    if 'full312_audit' in out.name:
                        r=dict(evidence_valid=True,full_round_complete=True,snapshot_samples=312,
                            archive_sha256=c.sha(post/'full312.zip'),scores={a:dict(scored_tasks=156,tool_errors=0) for a in ('A','C')},
                            totals={},decision='do_not_promote',rows=[])
                    else:r=dict(evidence_valid=True,pilot_complete=True,full_round_complete=False,snapshot_samples=24,
                                diagnostic_scores={},totals={},decision='do_not_expand_this_candidate')
                    c.save(out/'RESULTS.json',r)
                elif 'submit' in argv:
                    c.save(pilot/'queue_status.json',dict(complete=True,state='stopped_with_evidence' if mode=='pilot_failed' else 'complete',completed_samples=24))
                    return types.SimpleNamespace(returncode=0,stdout=json.dumps(dict(ticket=2,monitor_pid=123)),stderr='')
                return types.SimpleNamespace(returncode=0)
            fake_activity=types.SimpleNamespace(append=lambda *args:events.append(args))
            before=list(sys.path)
            try:
                with patch.object(c,'ROOT',post),patch.object(c,'RUN',run),patch.object(c,'PILOT',pilot),\
                    patch.object(c,'FULL_SPEC','wrong' if mode=='wrong_spec' else c.sha(run/'RUN_SPEC.json')),\
                    patch.object(c,'PILOT_SPEC',c.sha(pilot/'RUN_SPEC.json')),\
                    patch.object(c,'TOOLS',{n:c.sha(post/n) for n in ('audit.py','collect_evidence.py')}),\
                    patch('subprocess.run',side_effect=fake_command),patch.dict(sys.modules,activity=fake_activity):
                    if mode=='ok':c.main()
                    else:
                        with self.assertRaises((AssertionError,subprocess.CalledProcessError)):c.main()
                status=c.read(post/'continuation_status.json')
                submits=[a for a in commands if 'submit' in a]
                if mode in ('stop','wrong_spec','full_failed','audit_failed'):
                    self.assertEqual(submits,[])
                    self.assertFalse(status['complete'])
                else:
                    self.assertEqual(len(submits),1)
                    self.assertIn('fpga_owner_concise_output_',submits[0])
                    self.assertEqual(submits[0][-1],'queue')
                    self.assertEqual(status['complete'],mode=='ok')
                if mode=='ok':
                    self.assertEqual(status['state'],'full_and_pilot_audited')
                    self.assertEqual(len(events),3)
                if mode=='pilot_failed':self.assertEqual(len(commands),3)
            finally:sys.path[:]=before

    def test_stop_prevents_admission(self):self.execute('stop')
    def test_wrong_source_prevents_admission(self):self.execute('wrong_spec')
    def test_failed_full_prevents_admission(self):self.execute('full_failed')
    def test_audit_failure_prevents_admission(self):self.execute('audit_failed')
    def test_failed_pilot_is_not_retried(self):self.execute('pilot_failed')
    def test_valid_sequence_submits_once_and_audits_pilot(self):self.execute('ok')


if __name__=='__main__':unittest.main()
