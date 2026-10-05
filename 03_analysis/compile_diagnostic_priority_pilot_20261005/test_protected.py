"""Dynamic immutable-source groups, only own temporary fixtures."""
from pathlib import Path
import copy,hashlib,tempfile,unittest
from unittest.mock import patch
import protected_sources

sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

class Protected(unittest.TestCase):
    def material(self,root,count=3):
        groups={};roots={}
        for i in range(count):
            identity='FAKE_identity_'+str(i)+'_v2';p=root/identity;p.mkdir()
            (p/'RUN_SPEC_v2.json').write_text('FAKE spec '+str(i));(p/'worker.py').write_text('FAKE source '+str(i))
            groups[identity]=dict(cloud_root='/FAKE/cloud/'+identity,local_root=str(p),spec_name='RUN_SPEC_v2.json',
                spec_sha256=sha(p/'RUN_SPEC_v2.json'),source_hashes={'worker.py':sha(p/'worker.py')})
            roots[identity]=p
        return dict(schema='actual_score_protected_source_groups_v1',groups=groups,source_assets=count,model_calls=0,eda_calls=0),roots

    def test_variable_group_count_explicit_variant_roots_and_specnames(self):
        for count in [1,3]:
            with self.subTest(count=count),tempfile.TemporaryDirectory() as td:
                b,roots=self.material(Path(td),count);r=protected_sources.check(b,roots)
                self.assertEqual(r['source_assets'],count);self.assertEqual(set(r['groups']),set(b['groups']))

    def test_changed_source_or_spec_rejected(self):
        for name in ['worker.py','RUN_SPEC_v2.json']:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as td:
                b,roots=self.material(Path(td),1);(next(iter(roots.values()))/name).write_text('CHANGED')
                with self.assertRaises(AssertionError):protected_sources.check(b,roots)

    def test_bad_count_traversal_digest_or_missing_root_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            original,roots=self.material(Path(td),1)
            for mode in ['count','traversal','digest','missing']:
                with self.subTest(mode=mode):
                    b=copy.deepcopy(original);g=next(iter(b['groups'].values()))
                    if mode=='count':b['source_assets']=2
                    if mode=='traversal':g['source_hashes']={'../outside.py':'0'*64}
                    if mode=='digest':g['spec_sha256']='unknown'
                    with self.assertRaises(AssertionError):protected_sources.check(b,{} if mode=='missing' else roots)

    def test_link_component_rejected_without_reading_its_target(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'fixture';target.write_text('OWN fixture')
            with patch.object(Path,'is_symlink',lambda self:self==target):
                with self.assertRaises(AssertionError):protected_sources.sha(target)

if __name__=='__main__':unittest.main()
