"""Synthetic gate boundaries only; fixtures are not actual completed experiments."""
import hashlib
import types
import unittest
import metrics


TASKS=sorted(metrics.TARGETS+metrics.GUARDS)
EMPTY_SHA=hashlib.sha256(b'').hexdigest()


def rows():
    result=[]
    for task,arm in metrics.order(TASKS):
        level=3 if task in metrics.GUARDS else 0
        calls=2 if task in metrics.TARGETS else 1
        result.append(dict(task=task,arm=arm,solve_deadline_reached=False,solve_elapsed_s=1.,
            actual_model_requests=calls,received_model_responses=calls,
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
        if task in metrics.TARGETS:
            augmented=arm=='P';raw_sha=('9' if augmented else 'd')*64
            checks=[dict(attempt=0,outcome='fail',returncode=1,complete=True,measurement_valid=True,
                         code_sha256='c'*64,feedback_sha256=raw_sha,fact_identity_sha256='d'*64,
                         raw_multidriver_3818=True,model_feedback_sha256='e'*64 if augmented else raw_sha,
                         guidance_applied=augmented)]
            if augmented:
                checks.append(dict(attempt=1,outcome='pass',returncode=0,complete=True,measurement_valid=True,
                    code_sha256='f'*64,feedback_sha256=EMPTY_SHA,fact_identity_sha256=EMPTY_SHA,
                    raw_multidriver_3818=False,model_feedback_sha256=EMPTY_SHA,guidance_applied=False))
            else:
                checks.append(dict(attempt=1,outcome='fail',returncode=1,complete=True,measurement_valid=True,
                    code_sha256='b'*64,feedback_sha256='d'*64,fact_identity_sha256='d'*64,
                    raw_multidriver_3818=True,model_feedback_sha256='d'*64,guidance_applied=False))
        result.append(dict(task=task,arm=arm,first_reply_sha256='a'*64,
            original_repair_feedback_bound=True,elaboration_repair_feedback_bound=bool(checks),
            guidance_applied=bool(checks) and arm=='P',
            guidance_repair_feedback_bound=bool(checks) and arm=='P',elaboration_checks=checks))
    return result


def summarize(samples):
    assert len(samples)==8 and all(len(v)==1 for v in samples.values())
    return dict(tasks=8,scored_tasks=8,tool_errors=0,samples_per_task=1)


SCORER=types.SimpleNamespace(summarize=summarize)


class MetricTests(unittest.TestCase):
    def qualified_fixture(self):
        data=rows();improve(data,metrics.TARGETS[0]);return data,provenance()

    def decision(self,data,prov):
        return metrics.decision(metrics.aggregate(data,TASKS,SCORER),prov,data)

    def test_one_l0_to_l1_is_score_gain_with_fixed_denominator(self):
        data,prov=self.qualified_fixture();aggregate=metrics.aggregate(data,TASKS,SCORER)
        self.assertEqual(aggregate['coefficients'],{'C':.75,'P':.775})
        result=metrics.decision(aggregate,prov,data)
        self.assertTrue(result['qualified_for_new_full_regression'])
        self.assertEqual(result['matched_native_repair_tasks'],[metrics.TARGETS[0]])
        self.assertFalse(result['target_repair_chains'][0]['candidate_l3'])
        self.assertTrue(result['previous_full_gate_still_failed'])
        self.assertTrue(result['prior_elaboration_pilot_still_negative'])
        self.assertEqual(result['prior_elaboration_spec_sha256'],
                         '87cb93c00f386f3f16ece9f0ec9a7f49b18fd260faac9c75e83d4db9d31038bf')
        self.assertEqual(result['prior_elaboration_archive_sha256'],
                         '87e3d657ae500d7657fb98c509b8a48f1dafa7953dc243fa081dfec43d82a078')
        for name in ['adoption','independent_validation_qualified','five_sample_qualified']:
            self.assertFalse(result[name])

    def test_two_target_l3_not_required_but_preserved_separately(self):
        data,prov=self.qualified_fixture();improve(data,metrics.TARGETS[1],3)
        result=self.decision(data,prov)
        self.assertEqual(result['matched_native_repair_tasks'],metrics.TARGETS)
        self.assertTrue(result['target_repair_chains'][1]['candidate_l3'])

    def test_same_first_and_actual_guidance_repair_binding_required(self):
        mutations=[('first_reply_sha256','b'*64),('original_repair_feedback_bound',False),
                   ('elaboration_repair_feedback_bound',False),('guidance_repair_feedback_bound',False),
                   ('guidance_applied',False),('elaboration_checks',[])]
        for key,value in mutations:
            with self.subTest(key=key):
                data,prov=self.qualified_fixture();row(prov,metrics.TARGETS[0],'P')[key]=value
                self.assertFalse(self.decision(data,prov)['qualified_for_new_full_regression'])

    def test_both_arms_require_two_native_checks(self):
        for arm in ['C','P']:
            for count in [0,1,3]:
                with self.subTest(arm=arm,count=count):
                    data,prov=self.qualified_fixture();target=row(prov,metrics.TARGETS[0],arm)
                    checks=target['elaboration_checks']
                    target['elaboration_checks']=checks[:count] if count<2 else checks+[dict(checks[1])]
                    self.assertFalse(self.decision(data,prov)['qualified_for_new_full_regression'])

    def test_control_feedback_binding_and_absence_of_guidance_are_required(self):
        for key,value in [('original_repair_feedback_bound',False),
                          ('elaboration_repair_feedback_bound',False),
                          ('guidance_repair_feedback_bound',True)]:
            with self.subTest(key=key):
                data,prov=self.qualified_fixture();row(prov,metrics.TARGETS[0],'C')[key]=value
                self.assertFalse(self.decision(data,prov)['qualified_for_new_full_regression'])

    def test_both_first_checks_require_confirmed_multidriver_failure(self):
        mutations=[('attempt',1),('outcome','pass'),('returncode',0),('returncode',None),
                   ('returncode',True),('returncode',-9),('measurement_valid',False),
                   ('complete',False),('raw_multidriver_3818',False)]
        for arm in ['C','P']:
            for field,value in mutations:
                with self.subTest(arm=arm,field=field,value=value):
                    data,prov=self.qualified_fixture()
                    row(prov,metrics.TARGETS[0],arm)['elaboration_checks'][0][field]=value
                    self.assertFalse(self.decision(data,prov)['qualified_for_new_full_regression'])

    def test_first_native_source_and_path_normalized_facts_must_match(self):
        for field in ['code_sha256','fact_identity_sha256']:
            with self.subTest(field=field):
                data,prov=self.qualified_fixture()
                row(prov,metrics.TARGETS[0],'P')['elaboration_checks'][0][field]='8'*64
                self.assertFalse(self.decision(data,prov)['qualified_for_new_full_regression'])

    def test_owned_path_difference_in_raw_facts_does_not_deny_gate(self):
        data,prov=self.qualified_fixture()
        control=row(prov,metrics.TARGETS[0],'C')['elaboration_checks'][0]
        candidate=row(prov,metrics.TARGETS[0],'P')['elaboration_checks'][0]
        self.assertNotEqual(control['feedback_sha256'],candidate['feedback_sha256'])
        self.assertEqual(control['fact_identity_sha256'],candidate['fact_identity_sha256'])
        self.assertTrue(self.decision(data,prov)['qualified_for_new_full_regression'])

    def test_control_cannot_receive_guidance_and_candidate_must_receive_it(self):
        for location in ['control_sample','control_first','control_second','candidate_first']:
            with self.subTest(location=location):
                data,prov=self.qualified_fixture();control=row(prov,metrics.TARGETS[0],'C')
                candidate=row(prov,metrics.TARGETS[0],'P')
                if location=='control_sample':control['guidance_applied']=True
                elif location=='control_first':control['elaboration_checks'][0]['guidance_applied']=True
                elif location=='control_second':control['elaboration_checks'][1]['guidance_applied']=True
                else:candidate['elaboration_checks'][0]['guidance_applied']=False
                self.assertFalse(self.decision(data,prov)['qualified_for_new_full_regression'])

    def test_candidate_second_check_requires_confirmed_pass(self):
        for field,value in [('attempt',0),('returncode',1),('outcome','fail'),
                            ('measurement_valid',False),('complete',False)]:
            with self.subTest(field=field):
                data,prov=self.qualified_fixture()
                row(prov,metrics.TARGETS[0],'P')['elaboration_checks'][1][field]=value
                self.assertFalse(self.decision(data,prov)['qualified_for_new_full_regression'])

    def test_control_repair_can_fail_or_pass_without_changing_causal_requirement(self):
        data,prov=self.qualified_fixture()
        self.assertTrue(self.decision(data,prov)['qualified_for_new_full_regression'])
        second=row(prov,metrics.TARGETS[0],'C')['elaboration_checks'][1]
        second.update(outcome='pass',returncode=0,raw_multidriver_3818=False,
                      feedback_sha256=EMPTY_SHA,fact_identity_sha256=EMPTY_SHA,model_feedback_sha256=EMPTY_SHA)
        self.assertTrue(self.decision(data,prov)['qualified_for_new_full_regression'])

    def test_both_arms_use_only_the_original_two_model_requests(self):
        for arm in ['C','P']:
            with self.subTest(arm=arm):
                data,prov=self.qualified_fixture()
                row(data,metrics.TARGETS[0],arm).update(actual_model_requests=1,received_model_responses=1)
                self.assertFalse(self.decision(data,prov)['qualified_for_new_full_regression'])

    def test_native_chain_without_official_gain_is_not_qualified(self):
        data,prov=rows(),provenance();aggregate=metrics.aggregate(data,TASKS,SCORER)
        self.assertFalse(aggregate['screening_eligible'])
        result=metrics.decision(aggregate,prov,data)
        self.assertEqual(result['matched_native_repair_tasks'],[])
        self.assertFalse(result['qualified_for_new_full_regression'])

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
        data,prov=self.qualified_fixture()
        for task in metrics.GUARDS[:3]:row(data,task,'P').update(actual_model_requests=2,received_model_responses=2)
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
