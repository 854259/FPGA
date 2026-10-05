"""FAKE mutation and actual readonly metadata checks; no prepare/native/model calls."""
import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
import preparation_inputs,protected_sources
R=Path(__file__).absolute().parent
read=lambda name:json.loads((R/name).read_bytes())

class PreparationInputs(unittest.TestCase):
    def objects(self):
        return read('raw_evidence/ENVIRONMENT_CAPTURE.json'),read('raw_evidence/PROTECTED_GROUPS_CAPTURE.json'),read('INPUT_MANIFEST.json'),read('raw_evidence/source_binding/upstream_RUN_SPEC.json')
    def test_actual_current_capture_and_motivation_bound_without_execution(self):
        c,g,i,o=self.objects();counts=preparation_inputs.validate_capture(c,g,i,o)
        self.assertEqual(counts['protected_group_count'],len(g['groups']))
        self.assertEqual(counts['protected_source_assets'],sum(len(x['source_hashes']) for x in g['groups'].values()))
        m=preparation_inputs.validate_motivation(R)
        self.assertTrue(m['metadata_only']);self.assertFalse(m['model_input']);self.assertEqual(len(m['targets']),8)
    def test_actual_sources_checked_via_explicit_local_roots_only_on_windows(self):
        _,g,_,_=self.objects()
        if sys.platform!='win32':
            # Linux preflight must not try the Windows local_root or infer stripped directory names.
            self.assertTrue(all(x['cloud_root'].startswith('/workspace/') for x in g['groups'].values()))
            return
        roots={key:value['local_root'] for key,value in g['groups'].items()}
        result=protected_sources.check(g,roots=roots)
        self.assertTrue(result['verified']);self.assertEqual(result['source_assets'],g['source_assets'])
    def test_actual_earlier_capture_without_diagnostic_group_cannot_freeze(self):
        c,current,i,o=self.objects();g=copy.deepcopy(current)
        for key in list(g['groups']):
            if key.startswith('compile_diagnostic_priority_pilot_20261005'):
                del g['groups'][key]
        g['source_assets']=sum(len(x['source_hashes']) for x in g['groups'].values())
        with self.assertRaisesRegex(AssertionError,'Root must supply actual later installed groups'):
            preparation_inputs.validate_capture(c,g,i,o)
    def test_capture_counts_are_dynamic_but_not_fabricated_in_measurements(self):
        c,g,i,o=self.objects()
        fake=copy.deepcopy(g);first=next(iter(g['groups'].values()))
        fake['groups']['FAKE_EXTRA_SOURCE_GROUP_ONLY_FOR_PURE_TEST']=copy.deepcopy(first)
        fake['source_assets']+=len(first['source_hashes'])
        actual=preparation_inputs.validate_capture(c,fake,i,o)
        self.assertEqual(actual['protected_group_count'],len(g['groups'])+1)
        self.assertEqual(actual['protected_source_assets'],g['source_assets']+len(first['source_hashes']))
        fake['source_assets']+=1
        with self.assertRaises(AssertionError):preparation_inputs.validate_capture(c,fake,i,o)
    def test_changed_capture_model_dependency_and_input_bindings_rejected(self):
        c,g,i,o=self.objects()
        for kind in ['calls','dependency','input','identity']:
            bad=copy.deepcopy(c)
            if kind=='calls':bad['model_calls']=1
            if kind=='dependency':bad['dependency_hashes']['FAKE_extra_dependency']='0'*64
            if kind=='input':bad['protected']['tasks']['FAKE/task.txt']='0'*64
            if kind=='identity':bad['model_identity']['FAKE_extra_identity']='unused'
            with self.subTest(kind=kind),self.assertRaises(AssertionError):preparation_inputs.validate_capture(bad,g,i,o)
    def test_review_private_metadata_has_no_policy_file_access(self):
        actual_open=Path.open
        def policy_only(path,*a,**k):
            self.assertEqual(path.resolve(),(R/'APPENDIX.txt').resolve())
            return actual_open(path,*a,**k)
        with patch.object(Path,'open',new=policy_only):
            self.assertEqual(preparation_inputs.semantic_policy.appendix(R).encode('utf-8'),(R/'APPENDIX.txt').read_bytes())

if __name__=='__main__':unittest.main()
