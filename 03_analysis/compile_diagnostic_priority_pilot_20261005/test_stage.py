"""FAKE process orchestration; no model, real tools, guard or ledger execution."""
from pathlib import Path
import hashlib,json,shutil,sys,tempfile,types,unittest
from unittest.mock import patch
import pilot,metrics,worker,protected_sources

R=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
save=lambda p,v:p.write_text(json.dumps(v),encoding='utf-8')

class Stage(unittest.TestCase):
    def case(self,stop=False):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'raw_evidence').mkdir();kit=root/'kit'
            score=kit/'official_reference/selftest/score.py';score.parent.mkdir(parents=True)
            shutil.copyfile(R/'raw_evidence/test_fixtures/score.py',score)
            immutable=root/'FAKE_protected_v2';immutable.mkdir()
            (immutable/'RUN_SPEC_v2.json').write_text('FAKE immutable spec');(immutable/'source.py').write_text('FAKE source')
            b=dict(schema='actual_score_protected_source_groups_v1',model_calls=0,eda_calls=0,source_assets=1,
                groups={'FAKE_v2':dict(cloud_root='/FAKE/immutable_v2',local_root=str(immutable),spec_name='RUN_SPEC_v2.json',spec_sha256=sha(immutable/'RUN_SPEC_v2.json'),source_hashes={'source.py':sha(immutable/'source.py')})})
            save(root/'raw_evidence/NEXT_SCORE_PROTECTED_GROUPS.json',b)
            environment=dict(verified=True,vivado_bin='/FAKE/tools',udev_stub='/FAKE/stub',tools={},compiler_env={},udev_files={},model_calls=0,eda_calls=0)
            spec=dict(schema='compile_diag_priority_pilot_frozen_v1',identity='FAKE_DIAG_STAGE',arms=['C','P'],
                task_ids=sorted(metrics.TARGETS+metrics.COUNTEREXAMPLES+metrics.GUARDS),dependencies_cloud='/FAKE/deps',
                compiler_tools={},compiler_env={},udev_files={},minimum_disk_free_bytes=0,
                stage_timeout_s=14400,solve_deadline_s=300,max_actual_model_requests=32,model='fake')
            save(root/'RUN_SPEC.json',spec)
            calls=[];publications=[];activity_events=[]
            def command(argv,cwd,log,seconds):
                calls.append((argv,seconds));log.parent.mkdir(parents=True,exist_ok=True);log.write_text('FAKE command only')
                out=Path(argv[argv.index('--out')+1]);out.mkdir(parents=True)
                if Path(argv[2]).name=='worker.py':
                    self.assertEqual(seconds,300)
                    save(out/'requests.json',[dict(replayed=False,response_received=True)])
                    (out/'solution.v').write_text('FAKE solution')
                else:
                    self.assertEqual(seconds,360);self.assertEqual(argv[3],'judge')
                    task=argv[argv.index('--task')+1]
                    v=dict(task_id=task,level=3,coefficient=1.,tool_error=None)
                    save(out/'bound_verdict.json',dict(solution_sha256='FAKE',verdict_sha256='FAKE',verdict=v))
                return dict(returncode=0,timeout=False,launch_error=None,remaining_live_group=[],elapsed_s=.01,
                    log_sha256=sha(log),log_bytes=log.stat().st_size)
            paired=types.SimpleNamespace(check_resource=lambda *a,**k:None,model_idle=lambda *a:None,owned_command=command)
            original_load=pilot.load
            def load(name,path):return paired if name=='fresh_owned' else original_load(name,path)
            activity=types.SimpleNamespace(append=lambda *a:activity_events.append(a))
            real_check=protected_sources.check
            def check(binding):return real_check(binding,roots={'FAKE_v2':immutable})
            if stop:(root/'STOP_AFTER_CURRENT').write_text('stop before first model')
            args=types.SimpleNamespace(kit=kit,resource_check=root/'guard/resource.json')
            fake_lib=types.SimpleNamespace(prctl=lambda *a:0)
            with patch.object(pilot,'ROOT',root),patch.object(pilot,'frozen',return_value=spec),patch.object(pilot,'validate_environment',return_value=environment),patch.object(pilot,'load',side_effect=load),patch.object(pilot,'publish',side_effect=lambda r:publications.append(dict(r))),patch.object(protected_sources,'check',side_effect=check),patch.object(pilot.sys,'platform','linux'),patch.object(pilot.ctypes,'CDLL',return_value=fake_lib),patch.dict(sys.modules,activity=activity),patch('subprocess.run',side_effect=AssertionError('unexpected real process')):
                rc=pilot.main(args)
            report=json.loads((root/'results/summary.json').read_bytes())
            checks=list((root/'results/protected_source_checks').glob('*.json'))
            if stop:
                self.assertEqual(rc,1);self.assertFalse(report['passed']);self.assertFalse(report['complete']);self.assertFalse(calls)
            else:
                self.assertEqual(rc,0);self.assertTrue(report['complete']);self.assertTrue(report['passed'])
                self.assertEqual(len(checks),34);self.assertEqual(len(calls),32)
                self.assertEqual([(r['task'],r['arm']) for r in report['rows']],metrics.order(spec['task_ids']))
                self.assertEqual(report['actual_model_requests'],16)
                self.assertFalse(report['adoption']);self.assertFalse(report['new_full_score'])
            self.assertTrue(publications);self.assertEqual(len(activity_events),1)

    def test_all16_original_budgeted_worker_judge_pairs_dynamic_protection(self):self.case()
    def test_boundary_stop_records_failure_before_fake_first_request(self):self.case(stop=True)

if __name__=='__main__':unittest.main()
