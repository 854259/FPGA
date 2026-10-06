"""One new current-scope control; prior nine methods are never rerun."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
import calibration
import stage

HERE=Path(__file__).resolve().parents[1]


class CurrentAnchorControl(unittest.TestCase):
    def test_current_inventory_rehashed_same_count_replacement_and_changed_anchor_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for folder in ('sources','dependencies'):
                for f in (HERE/folder).rglob('*.py'):
                    rel=f.relative_to(HERE);target=root/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(f.read_bytes())
            (root/'raw_evidence').mkdir()
            for n in ('PROTECTED_GROUPS_CAPTURE.json','PROTECTED_BASE_CAPTURE.json'):
                (root/'raw_evidence'/n).write_bytes((HERE/'raw_evidence'/n).read_bytes())
            plan=calibration.prepare(root/'prepared_cases')
            (root/'CASE_PLAN.json').write_bytes((root/'prepared_cases/CASE_PLAN.json').read_bytes())
            captured=stage.read(root/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json')
            declared={f.relative_to(root).as_posix():stage.digest(f) for f in root.rglob('*') if f.is_file()}
            spec=dict(schema='serial_timer_binary_event_native_frozen_v1',cloud_root=str(root.resolve()),source_hashes=declared,
                      model_requests_max=0,planned_controls=12,planned_native_commands=36,planned_guard_receipts=73,
                      planned_observations=plan['trace_observations'],native_command_timeout_s=30,stage_timeout_s=3600,
                      guard_timeout_s=4000,slot_minutes=70,protected_group_count=len(captured['groups']),
                      protected_source_assets=captured['source_assets'],production_sha256='9080c49a93c807a4e5291e729d0b3ccb85b8d78c680607510ebcec7192fa26d6')
            def save(path,j):Path(path).write_text(json.dumps(j,indent=2)+'\n',encoding='utf-8')
            save(root/'RUN_SPEC.json',spec)
            self.assertEqual(stage.frozen(root),(spec,plan))
            self.assertEqual(len(captured['groups']),108);self.assertEqual(captured['source_assets'],7269)
            base=stage.read(root/'raw_evidence/PROTECTED_BASE_CAPTURE.json');identity=next(iter(base['groups']))
            replacement=copy.deepcopy(captured)
            replacement['groups'][identity]['cloud_root']='/workspace/team/invalid_same_count_source_replacement_v1'
            self.assertEqual(len(replacement['groups']),len(captured['groups']))
            self.assertEqual(replacement['source_assets'],captured['source_assets'])
            self.assertEqual(sum(len(g['source_hashes']) for g in replacement['groups'].values()),captured['source_assets'])
            path=root/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json';save(path,replacement)
            forged=copy.deepcopy(spec);forged['source_hashes']['raw_evidence/PROTECTED_GROUPS_CAPTURE.json']=stage.digest(path)
            save(root/'RUN_SPEC.json',forged)
            with self.assertRaises(AssertionError):stage.frozen(root)
            # Forging the corresponding base and recomputing both source hashes
            # also fails against the immutable base-byte anchor in stage code.
            altered_base=copy.deepcopy(base);altered_base['groups'][identity]=replacement['groups'][identity]
            base_path=root/'raw_evidence/PROTECTED_BASE_CAPTURE.json';save(base_path,altered_base)
            forged['source_hashes']['raw_evidence/PROTECTED_BASE_CAPTURE.json']=stage.digest(base_path)
            save(root/'RUN_SPEC.json',forged)
            with self.assertRaises(AssertionError):stage.frozen(root)


if __name__=='__main__':unittest.main(verbosity=2)
