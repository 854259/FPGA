import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import pilot
from test_metrics import score,TASKS


class Stage(unittest.TestCase):
    def test_E_worker_selection_executes_real_original_functional_path(self):
        from test_fresh import Fresh
        calls,probes=Fresh().run_case('E',wrong=True)
        self.assertEqual((len(calls),len(probes)),(2,2))
        self.assertIn('least significant',calls[1]['messages'][1]['content'])

    def test_whole_job_schedules16_new_workers_and16_original_judges(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);commands=[]
            spec=dict(task_ids=TASKS,arms=['C','E'],schema='edge_feedback_pilot_frozen_v1',
                      model='fake',dependencies_cloud=str(root),identity='fake-pilot',
                      solve_deadline_s=300,stage_timeout_s=14400,max_actual_model_requests=32)
            (root/'RUN_SPEC.json').write_text(json.dumps(spec))
            def owned(argv,cwd,log,seconds):
                commands.append(argv);task=argv[argv.index('--task')+1]
                out=Path(argv[argv.index('--out')+1]);out.mkdir()
                if '--arm' in argv:
                    (out/'solution.v').write_text('fixture')
                    (out/'requests.json').write_text(json.dumps([dict(replayed=False,response_received=True)]*2))
                    self.assertEqual(seconds,300)
                else:
                    verdict=dict(task_id=task,level=3,coefficient=1.,tool_error=None,elapsed_s=1.)
                    (out/'bound_verdict.json').write_text(json.dumps(dict(solution_sha256='fixture',verdict_sha256='fixture',verdict=verdict)))
                    self.assertEqual(seconds,360)
                return dict(returncode=0,timeout=False,launch_error=None,remaining_live_group=[],elapsed_s=1.)
            paired=types.SimpleNamespace(check_resource=lambda *a,**k:None,owned_command=owned)
            loader=lambda name,path:score if name=='full_pinned_official_score' else paired
            import sys
            with patch.object(pilot,'ROOT',root),patch.object(pilot,'validate_environment',return_value=dict(verified=True,fixture_only=True)),patch.object(pilot,'frozen',return_value=spec),patch.object(pilot,'load',side_effect=loader),patch.object(pilot,'publish'),patch.object(pilot.sys,'platform','linux'),patch.object(pilot.ctypes,'CDLL',return_value=types.SimpleNamespace(prctl=lambda *a:0)),patch.dict(sys.modules,activity=types.SimpleNamespace(append=lambda *a:None)):
                self.assertEqual(pilot.main(types.SimpleNamespace(kit=root,resource_check=root/'resource.json')),0)
            report=json.loads((root/'results/summary.json').read_text())
            self.assertTrue(report['complete']);self.assertEqual(len(report['rows']),16)
            self.assertEqual(report['actual_model_requests'],32);self.assertEqual(len(commands),32)
            self.assertFalse(report['first_generation_replayed']);self.assertFalse(report['adoption'])
            sequence=[(a[a.index('--task')+1],a[a.index('--arm')+1]) for a in commands if '--arm' in a]
            self.assertEqual(sequence,pilot.metrics.order(TASKS))


if __name__=='__main__':unittest.main()
