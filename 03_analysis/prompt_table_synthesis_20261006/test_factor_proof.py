"""Reject altered upstream, changed fallback or modified skills before freeze."""
from pathlib import Path
import json,tempfile,unittest
import factor_proof

ROOT=Path(__file__).resolve().parent


class ExactSourceProof(unittest.TestCase):
    def fixture(self,target):
        copied=json.loads((ROOT/"COPY_PHASE_BASE.json").read_bytes())["copied_hashes"]
        names=list(copied)+["upstream/RUN_SPEC.json","COPY_PHASE_BASE.json",
            "baseline_worker.py","worker.py","contract.py","synthesis.py"]
        for name in names:
            src=ROOT/name;dst=Path(target)/name
            dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(src.read_bytes())

    def test_real_current_sources_bind_original_single_common_change(self):
        proof=factor_proof.verify(ROOT)
        self.assertEqual(proof["mechanical_route_actual_model_requests"],0)
        self.assertFalse(proof["new_execution_or_quality_proved"])
        self.assertEqual(len(proof["upstream_source_hashes"]),44)

    def test_upstream_or_copied_skill_tampering_rejected(self):
        for name in ["upstream/worker.py","package/skill/rtl-generation/SKILL.md"]:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as tmp:
                self.fixture(tmp);p=Path(tmp)/name;p.write_bytes(p.read_bytes()+b"\nchanged\n")
                with self.assertRaises(AssertionError):factor_proof.verify(tmp)

    def test_wrong_common_phase_or_changed_synthesizer_rejected(self):
        for name in ["baseline_worker.py","synthesis.py"]:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as tmp:
                self.fixture(tmp);p=Path(tmp)/name;p.write_bytes(p.read_bytes()+b"\n# changed\n")
                with self.assertRaises(AssertionError):factor_proof.verify(tmp)


if __name__=="__main__":
    unittest.main()
