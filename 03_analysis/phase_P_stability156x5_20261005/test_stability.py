"""FAKE development scores/activity; no external model/native/process execution."""
from pathlib import Path
import hashlib,json,types,unittest
import stability_metrics as m
from stability_worker import repeat_append
R=Path(__file__).resolve().parent
class Stability(unittest.TestCase):
    def fixture(self):
        tasks=['FAKE_'+str(i).zfill(3) for i in range(156)]
        rows=[dict(task=t,arm=a,repeat=p,actual_model_requests=1,received_model_responses=1,solve_deadline_reached=False,
            verdict=dict(task_id=t,tool_error=None,level=3,coefficient=1.)) for t,a,p in m.order(tasks)]
        scorer=types.SimpleNamespace(summarize=lambda values:dict(tasks=len(values),scored_tasks=len(values),tool_errors=0,samples_per_task=1))
        return tasks,rows,scorer
    def test_exact780_unique_allP_five_complete_passes(self):
        tasks,rows,s=self.fixture();self.assertEqual(len(rows),780);self.assertEqual(len(set(m.order(tasks))),780)
        self.assertEqual([r['repeat'] for r in rows[::156]],[1,2,3,4,5])
    def test_weighted_mean_keeps_failed_sample_without_best_selection(self):
        tasks,rows,s=self.fixture();rows[0]['verdict'].update(level=0,coefficient=0.)
        a=m.aggregate(rows,tasks,s);self.assertAlmostEqual(a['weighted_mean'],779/780)
        self.assertEqual(a['per_task'][0]['weighted_mean'],.8);self.assertEqual(a['levels'],{'0':1,'3':779})
    def test_missing_duplicate_reordered_or_bool_level_rejected(self):
        for mode in ['missing','duplicate','order','bool']:
            tasks,rows,s=self.fixture()
            if mode=='missing':rows.pop()
            if mode=='duplicate':rows[-1]=rows[0]
            if mode=='order':rows[0],rows[1]=rows[1],rows[0]
            if mode=='bool':rows[0]['verdict']['level']=True
            with self.subTest(mode=mode),self.assertRaises(AssertionError):m.aggregate(rows,tasks,s)
    def test_deadline_unknown_not_valid_five_measurement(self):
        tasks,rows,s=self.fixture();rows[0]['solve_deadline_reached']=True;rows[1]['received_model_responses']=0
        a=m.aggregate(rows,tasks,s);self.assertFalse(a['stability_measurement_valid']);self.assertEqual(a['unconfirmed_attempts'],1)
    def test_no_formal_five_adoption_or_expansion_qualification(self):
        tasks,rows,s=self.fixture();p=[dict(task=r['task'],arm=r['arm'],repeat=r['repeat']) for r in rows]
        d=m.decision(m.aggregate(rows,tasks,s),p,rows)
        for field in ['adoption','five_sample_qualified','formal_competition_five_qualified','independent_validation_qualified','qualified_for_new_full_regression']:self.assertFalse(d[field])
    def test_ledger_repeat_ids_unique_without_payload_message_mutation(self):
        events=[]
        for i in range(1,6):repeat_append(lambda *args:events.append(args),i)('own','calls','same-event','same-message',{'index':0})
        self.assertEqual(len({e[2] for e in events}),5)
        for i,e in enumerate(events,1):self.assertEqual(e[3],'same-message');self.assertEqual(e[4],dict(index=0,repeat=i))
        with self.assertRaises(AssertionError):repeat_append(lambda *a:None,True)
    def test_all44_original_phase_sources_and_pinned_spec_exact(self):
        c=json.loads((R/'STABILITY_SOURCE_COPY.json').read_bytes());self.assertEqual(len(c['copied_source_hashes']),44)
        for n,h in c['copied_source_hashes'].items():self.assertEqual(hashlib.sha256((R/n).read_bytes()).hexdigest(),h,n)
        self.assertEqual(c['phase_spec_sha256'],'3fb1531c14b011f80ff58de559e326a4904d3fbdbcf3cdce7d6c955285860ba1')
if __name__=='__main__':unittest.main()
