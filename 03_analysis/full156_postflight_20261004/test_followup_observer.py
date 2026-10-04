"""Metadata privacy and experiment identity checks; no model/tools."""
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent


class Observer(unittest.TestCase):
    def test_response_metadata_private_bodies_excluded_and_repeat_ids_stable(self):
        sp=importlib.util.spec_from_file_location('followup_check',HERE/'observe_followups.py');m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);pilot=root/'pilot1';post=root/'post';mapped=root/'map';ledger=root/'ledger';tickets=root/'tickets'
            for p in [pilot,post,mapped,ledger,tickets]:p.mkdir()
            def write(p,value):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value))
            write(pilot/'RUN_SPEC.json',dict(test=True));write(mapped/'RUN_SPEC.json',dict(test=True))
            write(pilot/'queue_status.json',dict(state='running',complete=False,completed_samples=1,current_task='task',current_arm='C'))
            write(post/'continuation_status.json',dict(state='observing_pilot',complete=False))
            folder=pilot/'samples/C/task/worker';q=folder/'requests/0'
            write(q/'request.json',dict(messages=[dict(content='PRIVATE_PROMPT_SENTINEL')]))
            write(q/'response.json',dict(id='response-test',usage=dict(prompt_tokens=12,completion_tokens=34),choices=[dict(finish_reason='stop',message=dict(content='PRIVATE_REPLY_SENTINEL'))]))
            write(folder/'requests.json',[dict(index=0,replayed=False,response_received=True,request_sha256=m.sha(q/'request.json'),response_sha256=m.sha(q/'response.json'),elapsed_s=1.2)])
            write(folder.parent/'accepted_row.json',dict(arm='C',task='task',solution_sha256='same-source',verdict=dict(level=3),solve_elapsed_s=2.,actual_model_requests=1,received_model_responses=1,solve_deadline_reached=False))
            entries=[];activity=types.SimpleNamespace(append=lambda *args:entries.append(args))
            with patch.object(m,'PILOT',pilot),patch.object(m,'POST',post),patch.object(m,'MAP',mapped),patch.object(m,'LEDGER',ledger),patch.object(m,'TICKETS',tickets):
                m.sync(activity);first=[e[2] for e in entries];entries.clear();m.sync(activity)
                self.assertEqual(first,[e[2] for e in entries])
                calls=[e for e in entries if e[1]=='calls'];self.assertEqual(len(calls),1)
                self.assertEqual(calls[0][-1]['tokens_out'],34)
                for entry in entries:json.dumps(entry[-1])
                public=json.dumps(entries,default=str)+(ledger/'STATUS.md').read_text()+(ledger/'SNAPSHOT.json').read_text()
                self.assertNotIn('PRIVATE_PROMPT_SENTINEL',public);self.assertNotIn('PRIVATE_REPLY_SENTINEL',public)
                # Same task/source under a different experiment must not merge.
                renamed=root/'pilot2';pilot.rename(renamed);entries.clear()
                with patch.object(m,'PILOT',renamed):m.sync(activity)
                self.assertTrue(set(first).isdisjoint(e[2] for e in entries))

    def test_unconfirmed_request_not_logged_as_response(self):
        sp=importlib.util.spec_from_file_location('followup_unconfirmed',HERE/'observe_followups.py');m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            for name in ['pilot','post','map','ledger','tickets']:(root/name).mkdir()
            def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v))
            write(root/'pilot/RUN_SPEC.json',{})
            write(root/'pilot/queue_status.json',dict(state='running',complete=False,completed_samples=0))
            write(root/'post/continuation_status.json',dict(state='observing_pilot',complete=False))
            write(root/'pilot/samples/A/task/worker/requests.json',[dict(index=0,replayed=False,response_received=False)])
            calls=[];activity=types.SimpleNamespace(append=lambda *args:calls.append(args))
            with patch.object(m,'PILOT',root/'pilot'),patch.object(m,'POST',root/'post'),patch.object(m,'MAP',root/'map'),patch.object(m,'LEDGER',root/'ledger'),patch.object(m,'TICKETS',root/'tickets'):
                m.sync(activity)
            self.assertEqual(calls,[])
            self.assertEqual(json.loads((root/'ledger/SNAPSHOT.json').read_text())['pilot_received_responses'],0)


if __name__=='__main__':unittest.main()
