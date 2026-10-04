import importlib.util
from pathlib import Path
import unittest

from complete_module_extract import extract_complete

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = load("extract_test_baseline", ROOT / "04_project/amd_rtl_agent/submission/baseline.py")
SELECTOR = load("extract_test_lexer", ROOT / "04_project/amd_rtl_agent/bench/signedness_selector.py")
GOOD = "module TopModule(input a, output z); assign z=a; endmodule"


class ExtractTests(unittest.TestCase):
    def extract(self, text):
        return extract_complete(text, BASE, SELECTOR._strip_noncode)

    def test_partial_fragment_before_complete_module(self):
        text = "Example:\n```verilog\nassign z=a;\n```\nFinal:\n```sv\n" + GOOD + "\n```"
        result, record = self.extract(text)
        self.assertEqual(result, GOOD + "\n")
        self.assertTrue(record["changed"])
        self.assertEqual(BASE.extract(text, "rtl"), "assign z=a;\n")

    def test_two_complete_answers_are_ambiguous(self):
        text = "```sv\n" + GOOD + "\n```\n```sv\n" + GOOD.replace("z=a", "z=~a") + "\n```"
        result, record = self.extract(text)
        self.assertEqual(result, BASE.extract(text, "rtl"))
        self.assertFalse(record["changed"])

    def test_plain_or_already_complete_preserves_baseline(self):
        for text in (GOOD, "```verilog\n" + GOOD + "\n```"):
            with self.subTest(text=text):
                result, record = self.extract(text)
                self.assertEqual(result, BASE.extract(text, "rtl"))
                self.assertFalse(record["changed"])

    def test_fake_keywords_in_comments_and_strings(self):
        block = '// module TopModule; endmodule\n' + GOOD.replace("assign z=a;", 'initial $display("endmodule module"); assign z=a;')
        result, record = self.extract("```sv\nassign z=a;\n```\n```sv\n" + block + "\n```")
        self.assertEqual(result, block.split("\n", 1)[1] + "\n")
        self.assertTrue(record["changed"])

    def test_malformed_or_multiple_modules_preserve_original(self):
        texts = ["```sv\n" + GOOD, "```sv\nmodule TopModule; /* unterminated\n```",
                 "```sv\n" + GOOD + "\nmodule Helper; endmodule\n```",
                 "```sv\nmodule TopModule;\n```\n```sv\n" + GOOD + "\n```"]
        for text in texts:
            with self.subTest(text=text):
                result, record = self.extract(text)
                self.assertEqual(result, BASE.extract(text, "rtl"))
                self.assertFalse(record["changed"])

    def test_non_verilog_fence_is_ignored(self):
        text = "```text\n" + GOOD + "\n```"
        result, record = self.extract(text)
        self.assertEqual(result, BASE.extract(text, "rtl"))
        self.assertFalse(record["changed"])


if __name__ == "__main__":
    unittest.main()
