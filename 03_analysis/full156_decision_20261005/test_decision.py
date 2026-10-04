"""Pure whole-denominator and mechanism attribution boundary cases."""
import copy,json,tempfile,unittest,hashlib,zipfile
from pathlib import Path
import decision

def observation(**kwargs):
    d={'coefficient':1,'first':'same-draft','replies':['same-draft'],'final':'same-source','deadline':False,'unconfirmed':0,'requests':1,'native_checks':[],'first_compile_pass':True,'first_compile_source':'same-compiled-source','forwarded_first_native_failure':False};d.update(kwargs);return d
def pairs():return [{'task':f't{i:03d}','A':observation(),'C':observation()} for i in range(156)]
def repair(p):p['A']['coefficient']=.2;p['C'].update(final='fixed-source',requests=2,replies=['same-draft','fixed-reply'],native_checks=[{'index':'map_check_0','status':'fail','mismatches':12}],forwarded_first_native_failure=True)

class Decision(unittest.TestCase):
    def test_matched_native_chain_preserves_all156_mean_and_no_deployment(self):
        p=pairs();repair(p[0]);r=decision.summarize(p,True);self.assertEqual(r['matched_native_repair_tasks'],['t000']);self.assertAlmostEqual(r['coefficient_mean_delta_all156'],.8/156);self.assertTrue(r['qualified_for_independent_validation_after_attribution']);self.assertFalse(r['adoption'])
    def test_non_native_positive_score_is_not_sufficient(self):
        p=pairs();p[0]['A']['coefficient']=.2;p[0]['C'].update(first='different-draft',replies=['different-draft'],final='different-source');r=decision.summarize(p,True);self.assertFalse(r['qualified_for_independent_validation_after_attribution']);self.assertAlmostEqual(r['coefficient_mean_delta_all156'],.8/156)
    def test_frozen_regression_gate_is_never_relaxed(self):
        p=pairs();repair(p[0]);p[1]['C']['coefficient']=.2;r=decision.summarize(p,False);self.assertFalse(r['qualified_for_independent_validation_after_attribution']);self.assertAlmostEqual(r['coefficient_mean_delta_all156'],0)
    def test_unmatched_initial_or_failed_compile_or_no_fact_does_not_claim_repair(self):
        for kind in ['first','first_compile_pass','first_compile_source','forwarded_first_native_failure']:
            p=pairs();repair(p[0]);p[0]['C'][kind]='different' if kind in ['first','first_compile_source'] else False
            with self.subTest(kind=kind):self.assertFalse(decision.summarize(p,True)['matched_native_repair_tasks'])
    def test_same_dut_judgment_change_and_unchanged_flow_anomaly_are_separate(self):
        p=pairs();p[0]['A']['coefficient']=.2;self.assertEqual(decision.summarize(p,True)['rows'][0]['category'],'same_dut_different_judgment')
        p=pairs();repair(p[0]);p[1]['C']['final']='changed-with-identical-replies';r=decision.summarize(p,True);self.assertEqual(r['unchanged_flow_anomalies'],['t001']);self.assertFalse(r['qualified_for_independent_validation_after_attribution'])
    def test_partial_and_duplicate_denominator_rejected(self):
        with self.assertRaises(AssertionError):decision.summarize(pairs()[:-1],True)
        p=pairs();p[-1]['task']=p[0]['task']
        with self.assertRaises(AssertionError):decision.summarize(p,True)
    def test_synthetic_and_deadline_never_expand_independent_validation(self):
        p=pairs();repair(p[0]);self.assertFalse(decision.summarize(p,True,fixture=True)['qualified_for_independent_validation_after_attribution'])
        p[0]['C']['deadline']=True;self.assertFalse(decision.summarize(p,False)['matched_native_repair_tasks'])
    def test_historical_or_partial_audit_cannot_enter_processor(self):
        for evidence in [{'evidence_valid':True,'full156_evidence_valid':False,'historical_fixture_only':True},{'evidence_valid':False}]:
            with tempfile.TemporaryDirectory(prefix='decision-boundary-') as td:
                p=Path(td)/'audit.json';p.write_text(json.dumps(evidence),encoding='utf-8')
                with self.assertRaises(AssertionError):decision.process(Path(td)/'never_read.zip',p)
    def test_complete_archive_parser_and_synthetic_production_rejection(self):
        spec_path=decision.ROOT.parent/'functional_full156_20261005/RUN_SPEC.json'
        spec=json.loads(spec_path.read_text(encoding='utf-8'))
        self.assertEqual(decision.sha(spec_path),decision.SPEC_SHA)
        content='synthetic source-only draft';identity=hashlib.sha256(content.encode()).hexdigest()
        with tempfile.TemporaryDirectory(prefix='decision-complete-fixture-') as td:
            archive=Path(td)/'fixture.zip';audit=Path(td)/'audit.json';rows=[];provenance=[]
            with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
                def put(name,value):z.writestr(name,json.dumps(value))
                put('ARCHIVE_MANIFEST.json',{'schema':'functional_fresh_archive_v1','run_spec_sha256':decision.SPEC_SHA,'synthetic_fixture':True})
                z.writestr('run/RUN_SPEC.json',spec_path.read_bytes())
                for task in spec['task_ids']:
                    for arm in ['A','C']:
                        prefix=f'run/results/samples/{arm}/{task}/worker/'
                        rows.append({'task':task,'arm':arm,'actual_model_requests':1,'received_model_responses':1,'verdict':{'coefficient':1},'solution_sha256':'synthetic-final','solve_deadline_reached':False})
                        provenance.append({'task':task,'arm':arm,'first_reply_sha256':identity,'native_checks':[]})
                        put(prefix+'requests.json',[{'response_received':True}])
                        put(prefix+'requests/0/request.json',{'model':spec['model'],'max_tokens':8192,'temperature':0,'top_p':1,'messages':[]})
                        put(prefix+'requests/0/response.json',{'choices':[{'message':{'content':content}}]})
                        put(prefix+'compile_journal.json',[{'argv':['xvlog','/synthetic/compile-0/solution.v'],'returncode':0,'timeout':False,'source_before_sha256':'synthetic-final'}])
                put('run/results/summary.json',{'complete':True,'passed':True,'rows':rows})
            e={'evidence_valid':True,'full156_evidence_valid':True,'historical_fixture_only':False,'spec_sha256':decision.SPEC_SHA,'expected_samples':312,'archive_sha256':decision.sha(archive),'auditor_sha256':decision.sha(decision.ROOT.parent/'functional_full156_20261005/audit.py'),'provenance':provenance,'candidate_qualified_for_independent_validation':True,'coefficients':{'A':1,'C':1},'official_scores':{'A':1,'C':1},'regressions':[],'requests_by_arm':{'A':156,'C':156},'solve_seconds_by_arm':{'A':0,'C':0}}
            audit.write_text(json.dumps(e),encoding='utf-8')
            with self.assertRaises(AssertionError):decision.process(archive,audit)
            r=decision.process(archive,audit,fixture=True)
            self.assertEqual(len(r['rows']),156);self.assertFalse(r['actual_full_result_processed']);self.assertFalse(r['qualified_for_independent_validation_after_attribution'])
            e['coefficients']['C']=.5;audit.write_text(json.dumps(e),encoding='utf-8')
            with self.assertRaises(AssertionError):decision.process(archive,audit,fixture=True)

if __name__=='__main__':unittest.main()
