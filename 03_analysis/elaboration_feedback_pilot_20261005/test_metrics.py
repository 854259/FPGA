"""Synthetic gate boundaries only; fixtures are not actual completed experiments."""
import copy
import types
import unittest
import metrics


TASKS=sorted(metrics.TARGETS+metrics.GUARDS)


def rows():
    result=[]
    for task,arm in metrics.order(TASKS):
        level=3 if task in metrics.GUARDS else 0
        result.append(dict(task=task,arm=arm,solve_deadline_reached=False,solve_elapsed_s=1.,
            actual_model_requests=1,received_model_responses=1,
            verdict=dict(task_id=task,level=level,coefficient=metrics.COEFFICIENTS[level],tool_error=None)))
    return result


def row(data,task,arm):
    return next(x for x in data if (x['task'],x['arm'])==(task,arm))


def improve(data,task,level=1):
    target=row(data,task,'P');target['verdict'].update(level=level,coefficient=metrics.COEFFICIENTS[level])
    target.update(actual_model_requests=2,received_model_responses=2)


def provenance():
    result=[]
    for task,arm in metrics.order(TASKS):
        checks=[]
        if arm=='P' and task in metrics.TARGETS:
            checks=[dict(attempt=0,outcome='fail',returncode=1,complete=True,measurement_valid=True),
                    dict(attempt=1,outcome='pass',returncode=0,complete=True,measurement_valid=True)]
        result.append(dict(task=task,arm=arm,first_reply_sha256='a'*64,
            original_repair_feedback_bound=True,elaboration_repair_feedback_bound=bool(checks),
            elaboration_checks=checks))
    return result


def summarize(samples):
    assert len(samples)==8 and all(len(v)==1 for v in samples.values())
    return dict(tasks=8,scored_tasks=8,tool_errors=0,samples_per_task=1)


SCORER=types.SimpleNamespace(summarize=summarize)


class MetricTests(unittest.TestCase):
    def qualified_fixture(self):
        data=rows();improve(data,metrics.TARGETS[0]);return data,provenance()

    def test_one_l0_to_l1_is_score_gain_with_fixed_denominator(self):
        data,prov=self.qualified_fixture();aggregate=metrics.aggregate(data,TASKS,SCORER)
        self.assertEqual(aggregate['coefficients'],{'C':.75,'P':.775})
        result=metrics.decision(aggregate,prov,data)
        self.assertTrue(result['qualified_for_new_full_regression'])
        self.assertEqual(result['matched_native_repair_tasks'],[metrics.TARGETS[0]])
        self.assertFalse(result['target_repair_chains'][0]['candidate_l3'])
        self.assertTrue(result['previous_full_gate_still_failed'])
        for name in ['adoption','independent_validation_qualified','five_sample_qualified']:
            self.assertFalse(result[name])

    def test_two_target_l3_not_required_but_preserved_separately(self):
        data,prov=self.qualified_fixture();improve(data,metrics.TARGETS[1],3)
        result=metrics.decision(metrics.aggregate(data,TASKS,SCORER),prov,data)
        self.assertEqual(result['matched_native_repair_tasks'],metrics.TARGETS)
        self.assertTrue(result['target_repair_chains'][1]['candidate_l3'])

    def test_same_first_and_exact_repair_chain_required(self):
        mutations=[('first_reply_sha256','b'*64),('original_repair_feedback_bound',False),
                   ('elaboration_repair_feedback_bound',False),('elaboration_checks',[])]
        for key,value in mutations:
            with self.subTest(key=key):
                data,prov=self.qualified_fixture();row(prov,metrics.TARGETS[0],'P')[key]=value
                self.assertFalse(metrics.decision(metrics.aggregate(data,TASKS,SCORER),prov,data)['qualified_for_new_full_regression'])

    def test_actual_first_failure_then_second_success_required(self):
        for index,field,value in [(0,'returncode',0),(0,'outcome','pass'),(1,'returncode',1),
                                   (1,'outcome','fail'),(0,'measurement_valid',False),(1,'complete',False)]:
            with self.subTest(index=index,field=field):
                data,prov=self.qualified_fixture()
                row(prov,metrics.TARGETS[0],'P')['elaboration_checks'][index][field]=value
                self.assertFalse(metrics.decision(metrics.aggregate(data,TASKS,SCORER),prov,data)['qualified_for_new_full_regression'])

    def test_deadline_or_unconfirmed_preserves_rows_but_denies_gate(self):
        for kind in ['deadline','unconfirmed']:
            data,prov=self.qualified_fixture();target=row(data,metrics.TARGETS[1],'P')
            if kind=='deadline':target['solve_deadline_reached']=True
            else:target['received_model_responses']=0
            aggregate=metrics.aggregate(data,TASKS,SCORER)
            self.assertFalse(aggregate['screening_eligible'])
            self.assertFalse(metrics.decision(aggregate,prov,data)['qualified_for_new_full_regression'])
            self.assertEqual(aggregate['official_scores']['P']['tasks'],8)

    def test_guard_l3_and_same_calls_required(self):
        for kind in ['level','calls']:
            data,prov=self.qualified_fixture();target=row(data,metrics.GUARDS[0],'P')
            if kind=='level':target['verdict'].update(level=1,coefficient=.2)
            else:target.update(actual_model_requests=2,received_model_responses=2)
            self.assertFalse(metrics.aggregate(data,TASKS,SCORER)['screening_eligible'])

    def test_regression_or_more_than_two_added_calls_denies_gate(self):
        data,prov=self.qualified_fixture();row(data,metrics.TARGETS[1],'C')['verdict'].update(level=1,coefficient=.2)
        self.assertFalse(metrics.aggregate(data,TASKS,SCORER)['screening_eligible'])
        data,prov=self.qualified_fixture();improve(data,metrics.TARGETS[1]);row(data,metrics.GUARDS[1],'P').update(actual_model_requests=2,received_model_responses=2)
        self.assertFalse(metrics.aggregate(data,TASKS,SCORER)['screening_eligible'])

    def test_partial_wrong_order_or_tool_error_cannot_be_aggregate(self):
        for kind in ['partial','order','tool_error']:
            data=rows()
            if kind=='partial':data.pop()
            elif kind=='order':data.reverse()
            else:data[0]['verdict']['tool_error']='synthetic failure'
            with self.assertRaises(AssertionError):metrics.aggregate(data,TASKS,SCORER)

    def test_score_level_mapping_unchanged(self):
        self.assertEqual(metrics.COEFFICIENTS,{0:0.,1:.2,2:.7,3:1.})
        data=rows();data[0]['verdict']['coefficient']=.7
        with self.assertRaises(AssertionError):metrics.aggregate(data,TASKS,SCORER)


if __name__=='__main__':unittest.main()
