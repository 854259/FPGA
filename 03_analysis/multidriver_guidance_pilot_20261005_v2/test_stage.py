import json
from pathlib import Path
import tempfile,types,unittest
from unittest.mock import patch
import pilot

TASKS=sorted(['Prob045_edgedetect2','Prob054_edgedetect','Prob058_alwaysblock2',
              'Prob071_always_casez','Prob112_always_case2','Prob115_shift18',
              'Prob133_2014_q3fsm','Prob156_review2015_fancytimer'])

def summarize(verdicts):
    return dict(tasks=len(verdicts),scored_tasks=len(verdicts),tool_errors=0,
                samples_per_task=1)

class Stage(unittest.TestCase):
    def test_same300s16_fresh_workers_original_judges_and_controls_first(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);commands=[];events=[]
            spec=dict(task_ids=TASKS,arms=['C','P'],schema='multidriver_guidance_pilot_frozen_v1',
                      compiler_tools={},compiler_env={},udev_files={},model='fake',dependencies_cloud=str(root),identity='fake-elaboration',
                      solve_deadline_s=300,stage_timeout_s=14400,max_actual_model_requests=32)
            (root/'RUN_SPEC.json').write_text(json.dumps(spec))
            def owned(argv,cwd,log,seconds):
                self.assertEqual(events,['controls'])
                commands.append(argv);task=argv[argv.index('--task')+1]
                out=Path(argv[argv.index('--out')+1]);out.mkdir()
                if '--arm' in argv:
                    (out/'solution.v').write_text('fixture')
                    (out/'requests.json').write_text(json.dumps([dict(replayed=False,response_received=True)]))
                    self.assertEqual(seconds,300)
                else:
                    verdict=dict(task_id=task,level=3,coefficient=1.,tool_error=None,elapsed_s=1.)
                    (out/'bound_verdict.json').write_text(json.dumps(dict(solution_sha256='fixture',verdict_sha256='fixture',verdict=verdict)))
                    self.assertEqual(seconds,360)
                return dict(returncode=0,timeout=False,launch_error=None,remaining_live_group=[],elapsed_s=1.)
            paired=types.SimpleNamespace(check_resource=lambda *a,**k:None,owned_command=owned)
            scorer=types.SimpleNamespace(summarize=summarize)
            def loader(name,path):return scorer if name=='full_pinned_official_score' else paired
            import sys
            with patch.object(pilot,'ROOT',root),patch.object(pilot,'validate_environment',return_value=dict(verified=True,vivado_bin=str(root/'tools'),tools={},compiler_env={},udev_files={})),patch.object(pilot,'frozen',return_value=spec),patch.object(pilot,'load',side_effect=loader),patch.object(pilot,'publish'),patch.object(pilot,'verify_protected_sources') as protected_checks,patch.object(pilot.calibrate,'check',side_effect=lambda *a:events.append('controls')),patch.object(pilot.sys,'platform','linux'),patch.object(pilot.ctypes,'CDLL',return_value=types.SimpleNamespace(prctl=lambda *a:0)),patch.dict(sys.modules,activity=types.SimpleNamespace(append=lambda *a:None)):
                self.assertEqual(pilot.main(types.SimpleNamespace(kit=root,resource_check=root/'resource.json')),0)
            report=json.loads((root/'results/summary.json').read_text())
            self.assertTrue(report['complete']);self.assertTrue(report['passed'])
            self.assertEqual(len(report['rows']),16);self.assertEqual(report['actual_model_requests'],16)
            self.assertEqual(len(commands),32);self.assertFalse(report['first_generation_replayed'])
            self.assertFalse(report['adoption'])
            self.assertEqual(protected_checks.call_count,35)
            self.assertEqual([call.args[1] for call in protected_checks.call_args_list],list(range(35)))
            self.assertEqual([(a[a.index('--task')+1],a[a.index('--arm')+1]) for a in commands if '--arm' in a],pilot.metrics.order(TASKS))

if __name__=='__main__':unittest.main()
