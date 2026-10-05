"""Task-name admission against immutable upstream membership and input binding."""
from pathlib import Path
import json,tempfile,unittest
import preparation_inputs


class TaskAdmission(unittest.TestCase):
    def fixture(self,root):
        upstream=Path(root)/"upstream";upstream.mkdir()
        ids=[f"Prob{i:03d}_fixture" for i in range(1,157)]
        (upstream/"RUN_SPEC.json").write_text(json.dumps(dict(task_ids=ids)),encoding="utf-8")
        inputs={t+"/prompt.txt":"0"*64 for t in ids}
        (upstream/"INPUT_MANIFEST.json").write_text(json.dumps(dict(input_sha256=inputs)),encoding="utf-8")
        return upstream

    def test_unique_membership_and_full_fixed_sample_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.fixture(tmp);g=preparation_inputs.task_groups(tmp)
            self.assertEqual((len(g["target_tasks"]),len(g["guard_tasks"]),len(g["abstention_tasks"]),g["expected_samples"]),(6,7,1,28))
            self.assertEqual(g["task_ids"],sorted(g["task_ids"]))

    def test_missing_or_duplicate_number_rejected(self):
        for duplicate in [False,True]:
            with self.subTest(duplicate=duplicate),tempfile.TemporaryDirectory() as tmp:
                upstream=self.fixture(tmp);p=upstream/"RUN_SPEC.json";s=json.loads(p.read_bytes())
                s["task_ids"][82]="Prob050_duplicate" if duplicate else "Other083_missing"
                p.write_text(json.dumps(s),encoding="utf-8")
                with self.assertRaises(AssertionError):preparation_inputs.task_groups(tmp)

    def test_prompt_name_must_be_bound_not_just_suggested(self):
        with tempfile.TemporaryDirectory() as tmp:
            upstream=self.fixture(tmp);p=upstream/"INPUT_MANIFEST.json";s=json.loads(p.read_bytes())
            del s["input_sha256"]["Prob083_fixture/prompt.txt"]
            p.write_text(json.dumps(s),encoding="utf-8")
            with self.assertRaises(AssertionError):preparation_inputs.task_groups(tmp)


if __name__=="__main__":
    unittest.main()
