"""Read-only source/admission controls, compatible before and after freeze."""
from pathlib import Path
import hashlib,json,unittest
import factor_proof,protected_sources

R=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

class Source(unittest.TestCase):
    def test_shared_worker_single_stdout_factor_and_all_copied_phase_assets(self):
        p=factor_proof.verify(R)
        self.assertTrue(p['same_worker_both_arms']);self.assertTrue(p['successful_ansi_patch_early_return_unchanged'])
        self.assertFalse(p['real_execution_proved']);self.assertEqual(len(p['unchanged_assets']),25)

    def test_priority_original_frozen_bytes_and_runtime_cap_kept(self):
        self.assertEqual(sha(R/'priority.py'),factor_proof.PRIORITY_SHA)
        self.assertEqual(sha(R/'package/agent/map_runtime.py'),'2f7cb98bc44a9e100d36ca12ac4ef7bf9ae2535473da358e166afa2559e96cba')
        self.assertEqual(sha(R/'package/skill/rtl-generation/SKILL.md'),'f4c4c8e2d97ec476b1282dd517f5c5008a497c4a03b36996fdabb27cf1cabd01')

    def test_existing_actual_capture_schema_and_dynamic_manifest_binding(self):
        c=json.loads((R/'raw_evidence/NEXT_SCORE_ENVIRONMENT_CAPTURE.json').read_bytes())
        self.assertEqual(c['schema'],'actual_diagnostic_next_readonly_environment_capture_v1')
        self.assertEqual(c['model_calls'],0);self.assertEqual(c['eda_calls'],0)
        b=json.loads((R/'raw_evidence/NEXT_SCORE_PROTECTED_GROUPS.json').read_bytes())
        self.assertEqual(protected_sources.validate(b),sum(len(g['source_hashes']) for g in b['groups'].values()))
        phase=b['groups']['phase_full156_20261005_v1']
        self.assertEqual(phase['spec_sha256'],'3fb1531c14b011f80ff58de559e326a4904d3fbdbcf3cdce7d6c955285860ba1')
        self.assertEqual(c['protected']['tasks'],json.loads((R/'INPUT_MANIFEST.json').read_bytes())['input_sha256'])

if __name__=='__main__':unittest.main()
