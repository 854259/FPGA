"""FAKE20sample stage scheduling, never native/model/quality evidence."""
import json,tempfile,types,unittest,sys
from pathlib import Path
from unittest.mock import patch
import pilot,metrics
TASKS=sorted(metrics.TARGETS+metrics.GUARDS)
class Stage(unittest.TestCase):
    def test_exact20fresh_original300s_workers_judges_and41_source_checks(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);commands=[]
            s=dict(task_ids=TASKS,arms=['C','P'],schema='bit_mapping_guidance_pilot_frozen_v1',model='fake',dependencies_cloud=str(root),identity='fake-bit',solve_deadline_s=300,stage_timeout_s=14400,max_actual_model_requests=40,minimum_disk_free_bytes=0,compiler_tools={},compiler_env={},udev_files={})
            (root/'RUN_SPEC.json').write_text(json.dumps(s))
            def owned(argv,cwd,log,seconds):
                commands.append(argv);task=argv[argv.index('--task')+1];out=Path(argv[argv.index('--out')+1]);out.mkdir()
                if '--arm' in argv:
                    (out/'solution.v').write_text('FAKE');(out/'requests.json').write_text(json.dumps([dict(replayed=False,response_received=True)]));self.assertEqual(seconds,300)
                else:
                    v=dict(task_id=task,level=3,coefficient=1.,tool_error=None,elapsed_s=1.);(out/'bound_verdict.json').write_text(json.dumps(dict(solution_sha256='fake',verdict_sha256='fake',verdict=v)));self.assertEqual(seconds,360)
                return dict(returncode=0,timeout=False,launch_error=None,remaining_live_group=[],elapsed_s=1.)
            pair=types.SimpleNamespace(check_resource=lambda *a,**k:None,owned_command=owned)
            scorer=types.SimpleNamespace(summarize=lambda v:dict(tasks=10,scored_tasks=10,tool_errors=0,samples_per_task=1))
            loader=lambda name,path:scorer if name=='full_pinned_official_score' else pair
            with patch.object(pilot,'ROOT',root),patch.object(pilot,'frozen',return_value=s),patch.object(pilot,'validate_environment',return_value=dict(verified=True,tools={},compiler_env={},udev_files={})),patch.object(pilot,'load',side_effect=loader),patch.object(pilot,'publish'),patch.object(pilot,'verify_protected_sources') as checks,patch.object(pilot.sys,'platform','linux'),patch.object(pilot.ctypes,'CDLL',return_value=types.SimpleNamespace(prctl=lambda *a:0)),patch.dict(sys.modules,activity=types.SimpleNamespace(append=lambda *a:None)):
                self.assertEqual(pilot.main(types.SimpleNamespace(kit=root,resource_check=root/'resource.json')),0)
            report=json.loads((root/'results/summary.json').read_bytes());self.assertEqual(len(report['rows']),20);self.assertEqual(len(commands),40)
            self.assertEqual([(r['task'],r['arm']) for r in report['rows']],metrics.order(TASKS));self.assertTrue(report['complete']);self.assertFalse(report['adoption'])
            self.assertEqual(checks.call_count,41);self.assertEqual([call.args[1] for call in checks.call_args_list],list(range(41)))
if __name__=='__main__':unittest.main()
