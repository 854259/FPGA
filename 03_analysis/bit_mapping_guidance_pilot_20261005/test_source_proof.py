"""Pure local byte and FAKE dynamic-source fixtures; not quality evidence."""
from pathlib import Path
import hashlib,json,tempfile,unittest
from unittest.mock import patch
import factor_proof,protected_sources
ROOT=Path(__file__).absolute().parent
class SourceProof(unittest.TestCase):
    def test_exact_common_worker_and_upstream_assets(self):
        result=factor_proof.verify(ROOT)
        self.assertTrue(result['transport_compile_budget_extract_runtime_skills_unchanged'])
        self.assertFalse(result['real_execution_proved'])
    def test_extra_worker_change_rejected(self):
        original=Path.read_text
        def changed(path,*a,**kw):
            text=original(path,*a,**kw)
            return text+'\n# FAKE extra factor\n' if path==ROOT/'worker.py' else text
        with patch.object(Path,'read_text',new=changed),self.assertRaises(AssertionError):
            factor_proof.verify(ROOT)
    def test_dynamic_groups_use_explicit_roots_and_actual_counts(self):
        with tempfile.TemporaryDirectory() as td:
            parent=Path(td);groups={};roots={}
            for index in range(10):
                root=parent/str(index);root.mkdir();(root/'RUN_SPEC.json').write_bytes(b'FAKE spec');(root/'source.py').write_bytes(b'FAKE source')
                key='FAKE_'+str(index);roots[key]=root
                groups[key]=dict(cloud_root='/FAKE_NOT_LOCAL/'+key,local_root=str(root),spec_name='RUN_SPEC.json',spec_sha256=hashlib.sha256(b'FAKE spec').hexdigest(),source_hashes={'source.py':hashlib.sha256(b'FAKE source').hexdigest()})
                if len(groups) in (8,10):
                    binding=dict(schema='actual_FAKE_dynamic_fixture_v1',groups=dict(groups),source_assets=len(groups),model_calls=0,eda_calls=0)
                    result=protected_sources.check(binding,roots=roots)
                    self.assertEqual(result['source_assets'],len(groups));self.assertEqual(len(result['groups']),len(groups))
                    wrong=dict(binding,source_assets=len(groups)+1)
                    with self.assertRaises(AssertionError):protected_sources.check(wrong,roots=roots)
            (roots['FAKE_9']/'source.py').write_bytes(b'FAKE changed source')
            with self.assertRaises(AssertionError):protected_sources.check(binding,roots=roots)
if __name__=='__main__':unittest.main()
