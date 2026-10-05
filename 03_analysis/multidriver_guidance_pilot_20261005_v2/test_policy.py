"""Pure policy/source-factor boundaries, no real model or native invocation."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import factor_proof
import guidance
import protected_sources
import worker

ROOT=Path(__file__).absolute().parent
FACT="ERROR: [VRFC 10-3818] variable 'observed' is driven by invalid combination of procedural drivers [/owned/candidate.sv:7]"


class Policy(unittest.TestCase):
    def test_control_original_facts_candidate_only_exact_appendix(self):
        self.assertEqual(worker.candidate_diagnostic('C',FACT),FACT)
        self.assertEqual(worker.candidate_diagnostic('P',FACT),FACT+guidance.APPENDIX)
        self.assertEqual(worker.candidate_diagnostic('P',FACT+guidance.APPENDIX),FACT+guidance.APPENDIX)
        for original in ['',FACT.replace('ERROR:', 'WARNING:'),FACT.replace('10-3818','10-1280')]:
            self.assertEqual(worker.candidate_diagnostic('C',original),original)
            self.assertEqual(worker.candidate_diagnostic('P',original),original)

    def test_exact_shared_worker_source_proof_and_unchanged_upstream_assets(self):
        result=factor_proof.verify(ROOT)
        self.assertTrue(result['same_worker_both_arms'])
        self.assertTrue(result['transport_compile_budget_extract_runtime_skills_unchanged'])
        self.assertFalse(result['real_execution_proved'])

    def test_changed_common_worker_code_cannot_pass_single_factor_proof(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'prepared';shutil.copytree(ROOT,root,ignore=shutil.ignore_patterns('__pycache__'))
            source=root/'worker.py';source.write_text(source.read_text(encoding='utf-8')+'\n# unregistered common modification\n',encoding='utf-8',newline='\n')
            with self.assertRaises(AssertionError):factor_proof.verify(root)

    def test_root_actual_eight_group_binding_matches_local_frozen_sources(self):
        binding=json.loads((ROOT/'raw_evidence/GUIDANCE_PROTECTED_GROUPS.json').read_bytes())
        roots={identity:(Path(group['cloud_root']) if Path(group['cloud_root']).is_dir() else ROOT.parent/identity.rsplit('_v',1)[0])
               for identity,group in binding['groups'].items()}
        result=protected_sources.check(binding,roots)
        self.assertTrue(result['verified']);self.assertEqual(result['source_assets'],232)
        bad=json.loads(json.dumps(binding));first=next(iter(bad['groups']))
        bad['groups'][first]['spec_sha256']='0'*64
        with self.assertRaises(AssertionError):protected_sources.check(bad,roots)


if __name__=='__main__':unittest.main()
