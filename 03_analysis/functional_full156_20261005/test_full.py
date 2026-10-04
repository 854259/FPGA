"""Full denominator and rejection controls; no inference or EDA."""
import importlib.util,copy,unittest,json,tempfile,types,sys
from unittest.mock import patch
from pathlib import Path
import metrics
import pilot
R=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('pinned_score_test',R/'raw_evidence/test_fixtures/score.py')
score=importlib.util.module_from_spec(s);s.loader.exec_module(score)


def material():
    tasks=['task%03d'%n for n in range(156)]
    rows=[dict(task=t,arm=a,verdict=dict(task_id=t,level=3,coefficient=1.,tool_error=None,elapsed_s=1.),
               actual_model_requests=1,received_model_responses=1,solve_deadline_reached=False,solve_elapsed_s=1.) for t,a in metrics.order(tasks)]
    return tasks,rows


class Full(unittest.TestCase):
    def test_real_stage_schedules_all312_beyond_small_pilot_budget(self):
        tasks,_=material()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for name in ['PRIORITY_CALIBRATION_AUDIT.json','SHIFT_CALIBRATION_AUDIT.json']:
                (root/name).write_text(json.dumps(dict(evidence_valid=True,controls_valid=True,natural_hypothesis_matched=True)))
            spec=dict(task_ids=tasks,model='fake',dependencies_cloud=str(root),identity='fake_full',stage_timeout_s=86400,
                      solve_deadline_s=300,max_actual_model_requests=624)
            (root/'RUN_SPEC.json').write_text(json.dumps(spec))
            (root/'FRESH_PILOT_AUDIT.json').write_text(json.dumps(dict(evidence_valid=True,candidate_qualified_for_full_regression=True)))
            (root/'BOUNDARY_RECONCILIATION.json').write_text(json.dumps(dict(passed=True)))
            commands=[]
            def owned(argv,cwd,log,seconds):
                task=argv[argv.index('--task')+1];commands.append(argv)
                if '--arm' in argv:
                    target=Path(argv[argv.index('--out')+1]);target.mkdir()
                    (target/'solution.v').write_text('fake')
                    (target/'requests.json').write_text(json.dumps([dict(replayed=False,response_received=True)]*2))
                else:
                    target=Path(argv[argv.index('--out')+1]);target.mkdir()
                    verdict=dict(task_id=task,level=3,coefficient=1.,tool_error=None,elapsed_s=1.)
                    (target/'bound_verdict.json').write_text(json.dumps(dict(solution_sha256='fake',verdict_sha256='fake',verdict=verdict)))
                return dict(returncode=0,timeout=False,launch_error=None,remaining_live_group=[],elapsed_s=1.)
            paired=types.SimpleNamespace(check_resource=lambda *a,**k:None,owned_command=owned)
            def loader(name,path):return score if name=='full_pinned_official_score' else paired
            fakec=types.SimpleNamespace(prctl=lambda *a:0)
            with patch.object(pilot,'ROOT',root),patch.object(pilot,'frozen',return_value=spec),patch.object(pilot,'load',side_effect=loader),patch.object(pilot,'publish'),patch.object(pilot.sys,'platform','linux'),patch.object(pilot.ctypes,'CDLL',return_value=fakec),patch.dict(sys.modules,activity=types.SimpleNamespace(append=lambda *a:None)):
                self.assertEqual(pilot.main(types.SimpleNamespace(kit=root,resource_check=root/'resource.json')),0)
            result=json.loads((root/'results/summary.json').read_text())
            self.assertEqual(len(result['rows']),312);self.assertEqual(result['actual_model_requests'],624)
            self.assertEqual(len(commands),624);self.assertTrue(result['complete'])
            self.assertEqual([(r['task'],r['arm']) for r in result['rows']],metrics.order(tasks))
    def test_full312_order_and_156_denominator(self):
        tasks,rows=material();r=metrics.aggregate(rows,tasks,score)
        self.assertEqual(len(rows),312);self.assertEqual(r['official_scores']['A']['scored_tasks'],156)
        self.assertFalse(r['candidate_qualified_for_independent_validation'])
        self.assertEqual(metrics.order(tasks)[:4],[(tasks[0],'A'),(tasks[0],'C'),(tasks[1],'C'),(tasks[1],'A')])
    def test_two_real_functional_improvements_allow_only_next_gate(self):
        tasks,rows=material()
        for row in rows:
            if row['task'] in tasks[10:12] and row['arm']=='A':row['verdict'].update(level=1,coefficient=.2)
            if row['task'] in tasks[10:12] and row['arm']=='C':row.update(actual_model_requests=2,received_model_responses=2)
        r=metrics.aggregate(rows,tasks,score);self.assertTrue(r['candidate_qualified_for_independent_validation'])
        self.assertAlmostEqual(r['coefficients']['C']-r['coefficients']['A'],1.6/156)
        # An original correct design regression disqualifies even a positive total.
        rows[5]['verdict'].update(level=1,coefficient=.2)
        self.assertFalse(metrics.aggregate(rows,tasks,score)['candidate_qualified_for_independent_validation'])
    def test_partial_duplicate_or_ordered_subset_never_scores(self):
        tasks,rows=material()
        for bad in [rows[:-1],rows+[rows[0]],list(reversed(rows))]:
            with self.assertRaises(AssertionError):metrics.aggregate(bad,tasks,score)
    def test_tools_deadlines_and_unconfirmed_never_promote(self):
        tasks,rows=material();rows[0]['verdict'].update(level=1,coefficient=.2)
        self.assertTrue(metrics.aggregate(rows,tasks,score)['candidate_qualified_for_independent_validation'])
        for field,value in [('solve_deadline_reached',True),('actual_model_requests',2)]:
            bad=copy.deepcopy(rows);bad[0][field]=value
            self.assertFalse(metrics.aggregate(bad,tasks,score)['candidate_qualified_for_independent_validation'])
        rows[0]['verdict']['tool_error']='environment failure'
        with self.assertRaises(AssertionError):metrics.aggregate(rows,tasks,score)


if __name__=='__main__':unittest.main()
