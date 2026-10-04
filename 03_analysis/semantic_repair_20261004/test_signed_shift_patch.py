import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "frozen_selector", ROOT / "04_project/amd_rtl_agent/bench/signedness_selector.py")
SELECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SELECTOR)
from signed_shift_patch import patch

PROMPT = ("An arithmetic shift register performs an arithmetic right shift. "
          "When disabled, hold its value. Initial contents are unspecified.")
SOURCE = """module TopModule(input clk, input load, input [7:0] data, output reg [7:0] q);
always @(posedge clk) begin
 if(load) q <= data;
 else q <= q >>> 1;
end
endmodule
"""


class PatchTests(unittest.TestCase):
    def test_exact_edit_and_second_application(self):
        updated, receipt = patch(PROMPT, SOURCE, SELECTOR)
        self.assertEqual(updated, SOURCE.replace("q >>> 1", "$signed(q) >>> 1"))
        self.assertTrue(receipt["changed"])
        again, receipt = patch(PROMPT, updated, SELECTOR)
        self.assertEqual(again, updated)
        self.assertFalse(receipt["changed"])

    def test_multiple_distances_keep_zero_and_control_logic(self):
        source = SOURCE.replace("else q <= q >>> 1;", """else begin
 q <= q >>> 0;
 if(data[0]) q <= q >>> 2;
 else q <= q >>> 8;
end""")
        updated, receipt = patch(PROMPT, source, SELECTOR)
        self.assertEqual(updated, source.replace("q >>> 2", "$signed(q) >>> 2")
                         .replace("q >>> 8", "$signed(q) >>> 8"))
        self.assertEqual(len(receipt["edits"]), 2)

    def test_comments_and_strings_keep_bytes(self):
        source = SOURCE.replace("else q <= q >>> 1;", """// q <= q >>> 1;
 else q <= /* q >>> 1; */ q >>> 1;""")
        updated, receipt = patch(PROMPT, source, SELECTOR)
        self.assertTrue(receipt["changed"])
        self.assertIn("// q <= q >>> 1;", updated)
        self.assertIn("/* q >>> 1; */ $signed(q) >>> 1;", updated)

    def test_unicode_comment_offsets(self):
        source = "// 中文注释\n" + SOURCE
        updated, receipt = patch(PROMPT, source, SELECTOR)
        self.assertTrue(receipt["changed"])
        self.assertEqual(updated, source.replace("q >>> 1", "$signed(q) >>> 1"))

    def test_ambiguous_same_line_is_unchanged(self):
        source = SOURCE.replace("else q <= q >>> 1;", "else begin q <= q >>> 1; q <= q >>> 1; end")
        updated, receipt = patch(PROMPT, source, SELECTOR)
        self.assertEqual(updated, source)
        self.assertFalse(receipt["changed"])

    def test_unsupported_and_correct_guards(self):
        cases = [
            (PROMPT, SOURCE.replace("reg [7:0]", "reg signed [7:0]")),
            (PROMPT, SOURCE.replace("q >>> 1", "$signed(q) >>> 1")),
            (PROMPT, SOURCE.replace("q >>> 1", "{q[7],q[7:1]}")),
            (PROMPT.replace("arithmetic", "logical"), SOURCE),
            (PROMPT, SOURCE.replace("q >>> 1", "q >> 1")),
            (PROMPT, SOURCE.replace("q >>> 1", "q >>> data")),
            (PROMPT, SOURCE.replace("q >>> 1", "q[7:0] >>> 1")),
            (PROMPT, SOURCE.replace("q >>> 1", "(q >>> 1) + 1")),
            (PROMPT, SOURCE.replace("[7:0]", "[WIDTH-1:0]")),
            (PROMPT + " Other modes use logical right shift.", SOURCE),
            (PROMPT, SOURCE + "/* unclosed"),
        ]
        for prompt, source in cases:
            with self.subTest(source=source):
                updated, receipt = patch(prompt, source, SELECTOR)
                self.assertEqual(updated, source)
                self.assertFalse(receipt["changed"])


if __name__ == "__main__":
    unittest.main()
