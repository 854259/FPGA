"""New serial native pipeline contexts only. Never invokes native tools/model."""
import copy
import ast
import re
import measure
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
import audit
import calibration
import stage

HERE=Path(__file__).resolve().parents[1]


def save(path,j):
    Path(path).write_text(json.dumps(j,indent=2)+'\n',encoding='utf-8')


def fixture(root):
    root=Path(root)
    for folder in ('sources','dependencies','raw_evidence'):
        for f in (HERE/folder).rglob('*'):
            if f.is_file():
                rel=f.relative_to(HERE);dest=root/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(f.read_bytes())
    plan=calibration.prepare(root/'prepared_cases');(root/'CASE_PLAN.json').write_bytes((root/'prepared_cases/CASE_PLAN.json').read_bytes())
    files={f.relative_to(root).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in root.rglob('*') if f.is_file()}
    spec=dict(schema='serial_timer_binary_event_native_frozen_v1',cloud_root=str(root.resolve()),source_hashes=files,
              model_requests_max=0,planned_controls=12,planned_native_commands=36,planned_guard_receipts=73,
              planned_observations=plan['trace_observations'],native_command_timeout_s=30,stage_timeout_s=3600,
              guard_timeout_s=4000,slot_minutes=70,protected_group_count=len(stage.read(root/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json')['groups']),protected_source_assets=stage.read(root/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json')['source_assets'],
              production_sha256='9080c49a93c807a4e5291e729d0b3ccb85b8d78c680607510ebcec7192fa26d6')
    save(root/'RUN_SPEC.json',spec)
    return spec,plan


class SerialPipelineControls(unittest.TestCase):
    def test_actual_synthetic_frozen_contract_reconstructs(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec,plan=fixture(tmp)
            self.assertEqual(stage.frozen(tmp),(spec,plan))
            self.assertEqual(plan['controls'],12);self.assertEqual(plan['native_calls_planned'],36)
            self.assertEqual(plan['guard_receipts_planned'],73)

    def test_same_inventory_rehashed_wrong_rtl_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec,plan=fixture(tmp);root=Path(tmp)
            n='prepared_cases/canonical_four/candidate.v';file=root/n
            b=file.read_bytes();self.assertIn(b"4'd7: _timer_next = 4'd8;",b)
            file.write_bytes(b.replace(b"4'd7: _timer_next = 4'd8;",b"4'd7: _timer_next = 4'd4;"))
            h=stage.digest(file);spec['source_hashes'][n]=h
            plan['rows'][2]['source_hashes']['candidate.v']=h
            save(root/'CASE_PLAN.json',plan);spec['source_hashes']['CASE_PLAN.json']=stage.digest(root/'CASE_PLAN.json')
            save(root/'RUN_SPEC.json',spec)
            with self.assertRaises(AssertionError):stage.frozen(root)

    def test_fixed_scope_deadlines_counts_and_production_identity_cannot_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            base,plan=fixture(tmp);root=Path(tmp)
            wrong={'planned_native_commands':35,'planned_controls':11,'planned_guard_receipts':72,
                   'planned_observations':plan['trace_observations']+1,'native_command_timeout_s':31,
                   'stage_timeout_s':3601,'guard_timeout_s':4001,'slot_minutes':71,
                   'protected_group_count':102,'protected_source_assets':7049,'model_requests_max':1,
                   'production_sha256':'0'*64}
            for key,value in wrong.items():
                with self.subTest(key=key):
                    modified=copy.deepcopy(base);modified[key]=value;save(root/'RUN_SPEC.json',modified)
                    with self.assertRaises(AssertionError):stage.frozen(root)

    def test_capture_scope_and_prepared_expected_inventory_rejected_if_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            base,plan=fixture(tmp);root=Path(tmp)
            cp=root/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json'
            capture=stage.read(cp);capture['source_assets']-=1;save(cp,capture)
            base['source_hashes']['raw_evidence/PROTECTED_GROUPS_CAPTURE.json']=stage.digest(cp)
            save(root/'RUN_SPEC.json',base)
            with self.assertRaises(AssertionError):stage.frozen(root)
        with tempfile.TemporaryDirectory() as tmp:
            base,plan=fixture(tmp);root=Path(tmp)
            n='prepared_cases/canonical_four/expected.json';p=root/n;e=stage.read(p)
            e[1]['outputs']='111';save(p,e);h=stage.digest(p);base['source_hashes'][n]=h
            plan['rows'][2]['source_hashes']['expected.json']=h
            save(root/'CASE_PLAN.json',plan);base['source_hashes']['CASE_PLAN.json']=stage.digest(root/'CASE_PLAN.json')
            save(root/'RUN_SPEC.json',base)
            with self.assertRaises(AssertionError):stage.frozen(root)

    def test_actual_context_negative_witnesses_strict_and_nonvacuous(self):
        for case in calibration.material():
            _,expected=calibration.testbench(case)
            row=dict(expect_mismatches=case['mutant'],witness=calibration.witness(case,expected))
            self.assertEqual(stage.witness(row,expected),row['witness'])
            if not case['mutant']:
                with self.assertRaises(AssertionError):stage.witness(dict(row,witness={}),expected)
            else:
                w=row['witness']
                for changed in (dict(w,index=-1),dict(w,field='next'),dict(w,offset=3),dict(w,actual=expected[w['index']]['outputs'][w['offset']])):
                    with self.assertRaises(AssertionError):stage.witness(dict(row,witness=changed),expected)

    def test_independent_auditor_fresh_serial_traces_and_refusals(self):
        case=calibration.material()[0];_,e=calibration.testbench(case)
        stream='\n'.join('TRACE '+str(i)+' '+r['next']+' '+r['outputs'] for i,r in enumerate(e))+'\nFINISH '+str(len(e))+' 0\n'
        result=audit.independently_measure(stream,e,False,None)
        self.assertEqual(result['observations'],len(e));self.assertEqual(result['mismatches'],[])
        for s in (stream.replace('TRACE 0','TRACE 1',1),stream.replace('FINISH','OTHER'),stream+'FATAL later\n',stream.replace(' 0\n',' 1\n')):
            with self.assertRaises(AssertionError):audit.independently_measure(s,e,False,None)
        case=calibration.material()[8];_,e=calibration.testbench(case);w=calibration.witness(case,e)
        wrong=copy.deepcopy(e);bits=list(wrong[w['index']]['outputs']);bits[w['offset']]=w['actual'];wrong[w['index']]['outputs']=''.join(bits)
        stream='\n'.join('TRACE '+str(i)+' '+r['next']+' '+r['outputs'] for i,r in enumerate(wrong))+'\nFINISH '+str(len(wrong))+' 1\n'
        result=audit.independently_measure(stream,e,True,w)
        self.assertEqual(result['mismatches'],[w['index']])
        with self.assertRaises(AssertionError):audit.independently_measure(stream,e,True,dict(w,actual=e[w['index']]['outputs'][w['offset']]))

    def test_native_command_arguments_scoped_to_scratch_and_fixed_order(self):
        spec=dict(compiler_tools={n:dict(path='/qualified/'+n) for n in ('xvlog','xelab','xsim')})
        self.assertEqual(stage.argv('xvlog',spec),['/qualified/xvlog','-sv','--nolog','candidate.v','tb.sv'])
        self.assertEqual(stage.argv('xelab',spec),['/qualified/xelab','tb','-s','serial_timer_snapshot','--nolog','-timescale','1ns/1ps'])
        self.assertEqual(stage.argv('xsim',spec),['/qualified/xsim','serial_timer_snapshot','-runall','-nolog'])

    def test_absent_or_extra_prepared_case_rows_cannot_pass_freeze(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec,plan=fixture(tmp);root=Path(tmp)
            for altered in (plan['rows'][:-1],plan['rows']+[plan['rows'][0]],list(reversed(plan['rows']))):
                modified=copy.deepcopy(plan);modified['rows']=altered;save(root/'CASE_PLAN.json',modified)
                spec['source_hashes']['CASE_PLAN.json']=stage.digest(root/'CASE_PLAN.json');save(root/'RUN_SPEC.json',spec)
                with self.assertRaises(AssertionError):stage.frozen(root)

    def test_protection_allows_complete_append_but_never_replacement_of_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec,plan=fixture(tmp);root=Path(tmp);extra=root/'extra_probe';extra.mkdir()
            save(extra/'witness.json',dict(sealed=True));h=stage.digest(extra/'witness.json')
            cp=root/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json';base=stage.read(cp)
            item=dict(cloud_root=str(extra.resolve()),spec_name='witness.json',spec_sha256=h,source_hashes={'witness.json':h})
            appended=copy.deepcopy(base);appended['groups']['new_extra_probe']=item;appended['source_assets']+=1
            save(cp,appended);spec['source_hashes']['raw_evidence/PROTECTED_GROUPS_CAPTURE.json']=stage.digest(cp)
            spec['source_hashes']['extra_probe/witness.json']=h
            spec['protected_group_count']=len(appended['groups']);spec['protected_source_assets']=appended['source_assets']
            save(root/'RUN_SPEC.json',spec);self.assertEqual(stage.frozen(root),(spec,plan))
            replaced=copy.deepcopy(base);identity=next(iter(replaced['groups']))
            old_assets=len(replaced['groups'][identity]['source_hashes'])
            replaced['groups'][identity]=item;replaced['source_assets']+=1-old_assets
            save(cp,replaced);spec['source_hashes']['raw_evidence/PROTECTED_GROUPS_CAPTURE.json']=stage.digest(cp)
            spec['protected_group_count']=len(replaced['groups']);spec['protected_source_assets']=replaced['source_assets']
            save(root/'RUN_SPEC.json',spec)
            with self.assertRaises(AssertionError):stage.frozen(root)


class NativeMaterialControls(unittest.TestCase):
    def test_finite_contract_variants_and_mutations(self):
        cases=calibration.material()
        self.assertEqual(len(cases),12)
        self.assertEqual(sum(not c['mutant'] for c in cases),8)
        positives=cases[:8]
        self.assertEqual({len(c['contract']['pattern']) for c in positives},{1,3,4,5,6,8,16})
        self.assertEqual({c['contract']['shift_cycles'] for c in positives},{1,2,4,5,7,9,32})
        self.assertEqual({c['contract']['clock_edge'] for c in positives},{'posedge','negedge'})
        self.assertEqual({c['contract']['reset_active'] for c in positives},{0,1})
        for c in cases[8:]:
            self.assertEqual(c['contract'],cases[2]['contract'])
            self.assertEqual(c['events'],cases[2]['events'])
            self.assertNotEqual(c['rtl'],cases[2]['rtl'])

    def test_active_and_opposite_edge_trace_schedule(self):
        for c in calibration.material():
            tb,expected=calibration.testbench(c)
            self.assertEqual(len(expected),3*len(c['events'])-1)
            indices=[int(n) for n in re.findall(r'\$display\("TRACE ([0-9]+) 0 %b"',tb)]
            self.assertEqual(indices,list(range(len(expected))))
            self.assertIn('FINISH '+str(len(expected))+' %0d',tb)
            for i,e in enumerate(c['events']):
                rows=[r for r in expected if r['event']==i]
                self.assertEqual([r['phase'] for r in rows],(['before_active_edge'] if i else [])+['after_active_edge','after_opposite_edge'])
                self.assertEqual(rows[-1]['outputs'],rows[-2]['outputs'])
                self.assertEqual(rows[-1]['outputs'],''.join(map(str,e['expected'])))
                if i:
                    self.assertEqual(rows[0]['outputs'],''.join(map(str,c['events'][i-1]['expected'])))

    def test_exact_shift_count_acknowledge_boundaries(self):
        for c in calibration.material()[:8]:
            rows=c['events'];tags={r['label']:i for i,r in enumerate(rows) if r['label']}
            a=tags['match_end'];b=tags['first_count']
            self.assertEqual(b-a,c['contract']['shift_cycles'])
            self.assertTrue(all(r['expected']==[1,0,0] for r in rows[a:b]))
            self.assertEqual(rows[b]['expected'],[0,1,0])
            self.assertEqual(rows[tags['early_ack_count']]['expected'],[0,1,0])
            self.assertEqual(rows[tags['completion']]['expected'],[0,0,1])
            self.assertEqual(rows[tags['done_hold']]['expected'],[0,0,1])
            self.assertEqual(rows[tags['acknowledge']]['expected'],[0,0,0])

    def test_synchronous_reset_observed_from_all_reachable_stages(self):
        for c in calibration.material()[:8]:
            expected_tags={'reset_prefix_'+str(q) for q in range(len(c['contract']['pattern']))}
            expected_tags|={'reset_shift_'+str(q) for q in range(c['contract']['shift_cycles'])}
            expected_tags|={'reset_count','reset_done'}
            selected=[r for r in c['events'] if r['label'] in expected_tags]
            self.assertEqual({r['label'] for r in selected},expected_tags)
            self.assertTrue(all(r['reset'] and r['expected']==[0,0,0] for r in selected))
            tb,observed=calibration.testbench(c)
            for r in observed:
                if c['events'][r['event']]['reset'] and r['phase']!='before_active_edge':
                    self.assertEqual(r['outputs'],'000')

    def test_nonvacuous_designated_mutant_witnesses_and_complete_trace_parser(self):
        for c in calibration.material()[8:]:
            tb,expected=calibration.testbench(c);w=calibration.witness(c,expected)
            wrong=copy.deepcopy(expected);i=w['index'];b=list(wrong[i]['outputs']);b[w['offset']]=w['actual'];wrong[i]['outputs']=''.join(b)
            stream='\n'.join('TRACE '+str(i)+' '+r['next']+' '+r['outputs'] for i,r in enumerate(wrong))+'\nFINISH '+str(len(wrong))+' 1\n'
            result=measure.measure(stream,expected,True,w)
            self.assertEqual(result['mismatches'],[i])
            with self.assertRaises(AssertionError):measure.measure(stream,expected,False)
            with self.assertRaises(AssertionError):measure.measure(stream.replace('FINISH','INVALID'),expected,True,w)
            with self.assertRaises(AssertionError):measure.measure(stream+'FINISH '+str(len(wrong))+' 1\n',expected,True,w)
            with self.assertRaises(AssertionError):measure.measure(stream,expected,True,dict(w,actual=expected[i]['outputs'][w['offset']]))

    def test_material_plan_binds_every_prepared_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'cases';p=calibration.prepare(root)
            self.assertEqual(p['controls'],12);self.assertEqual(p['native_calls_planned'],36)
            self.assertEqual(p['guard_receipts_planned'],73)
            self.assertEqual(p['trace_observations'],sum(r['observations'] for r in p['rows']))
            self.assertFalse(p['native_qualified']);self.assertFalse(p['score_measured'])
            self.assertEqual(json.loads((root/'CASE_PLAN.json').read_bytes()),p)
            import hashlib
            for row,c in zip(p['rows'],calibration.material()):
                for n,h in row['source_hashes'].items():
                    self.assertEqual(hashlib.sha256((root/row['relative_root']/n).read_bytes()).hexdigest(),h)
                _,e=calibration.testbench(c)
                self.assertEqual(json.loads((root/row['relative_root']/'expected.json').read_bytes()),e)
                self.assertEqual(row['witness'],calibration.witness(c,e))

    def test_independent_suffix_oracle_does_not_read_production_transition_table(self):
        root=Path(__file__).parent
        tree=ast.parse((root/'timer_fixture.py').read_bytes())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='RollingHistoryOracle')
        text=ast.unparse(cls)
        self.assertIn('endswith',text)
        self.assertIn('remaining -= 1',text)
        self.assertNotIn('search_transitions',text)
        self.assertNotIn('synthesize',text)
        self.assertNotIn('failure',text)

if __name__=='__main__':unittest.main(verbosity=2)
