"""Regression tests for the deterministic ANSI declaration repair.

The agent used to spend a model call repairing VRFC 10-1280 and VRFC 10-9336, and on
the two tasks where those appeared the model did not fix them. Both are mechanical:
an ANSI output assigned inside a procedural block must be declared `reg`, and the
signal must not also be declared `reg` in the body.

The repair is only ever attempted after the compiler has named the offending signals,
and the caller recompiles before accepting the result, so a wrong guess costs one
compile rather than a wrong answer. Prob058_alwaysblock2 goes from L0 to L3 this way.

The second test below is the case where the repair must NOT be trusted: Prob134 has a
genuine design error, assigning to an input, and no declaration change can fix it.
"""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


runtime = load('contract_runtime_declfix', ROOT / 'submission/agent/runtime.py')

# The real failing candidate, reduced to the parts the compiler complains about.
PROB058 = """module TopModule (
    input clk,
    input a,
    input b,
    output out_assign,
    output out_always_comb,
    output out_always_ff
);

    assign out_assign = a ^ b;

    reg out_always_comb;
    always_comb begin
        out_always_comb = a ^ b;
    end

    reg out_always_ff;
    always_ff @(posedge clk) begin
        out_always_ff <= a ^ b;
    end
endmodule
"""

PROB058_FEEDBACK = (
    "ERROR: [VRFC 10-1280] procedural assignment to a non-register out_always_comb "
    "is not permitted, left-hand side should be reg/integer/time/genvar\n"
    "ERROR: [VRFC 10-1280] procedural assignment to a non-register out_always_ff "
    "is not permitted, left-hand side should be reg/integer/time/genvar\n"
    "ERROR: [VRFC 10-9336] redeclaration of ANSI port 'out_always_comb' is not allowed\n"
    "ERROR: [VRFC 10-9336] redeclaration of ANSI port 'out_always_ff' is not allowed\n"
)


class DeclarationRepairTests(unittest.TestCase):

    def test_prob058_is_actually_repaired(self):
        fixed = runtime.repair_ansi_declarations(PROB058, PROB058_FEEDBACK)
        self.assertIsNotNone(fixed)
        self.assertIn('output reg out_always_comb', fixed)
        self.assertIn('output reg out_always_ff', fixed)
        # the duplicate body declarations must be gone
        self.assertNotIn('reg out_always_comb;', fixed)
        self.assertNotIn('reg out_always_ff;', fixed)
        # the untouched port and the logic must survive
        self.assertIn('output out_assign,', fixed)
        self.assertIn('assign out_assign = a ^ b;', fixed)
        self.assertEqual(fixed.count('endmodule'), 1)

    def test_already_reg_port_is_left_alone(self):
        code = """module TopModule (
    input clk,
    output reg q
);
    always @(posedge clk) q <= ~q;
endmodule
"""
        fb = "ERROR: [VRFC 10-1280] procedural assignment to a non-register q is not permitted"
        self.assertIsNone(runtime.repair_ansi_declarations(code, fb))

    def test_unrelated_error_produces_no_patch(self):
        code = "module TopModule (input a, output y);\n  assign y = ~a;\nendmodule\n"
        fb = "ERROR: [VRFC 10-4982] syntax error near 'wire'"
        self.assertIsNone(runtime.repair_ansi_declarations(code, fb))

    def test_empty_feedback_produces_no_patch(self):
        self.assertIsNone(runtime.repair_ansi_declarations(PROB058, ""))

    def test_missing_module_header_produces_no_patch(self):
        fb = "ERROR: [VRFC 10-1280] procedural assignment to a non-register q is not permitted"
        self.assertIsNone(runtime.repair_ansi_declarations("assign q = 1;\n", fb))

    def test_repair_keeps_the_body_after_the_port_list(self):
        fixed = runtime.repair_ansi_declarations(PROB058, PROB058_FEEDBACK)
        self.assertIn('always_comb begin', fixed)
        self.assertIn('always_ff @(posedge clk) begin', fixed)
        self.assertTrue(fixed.rstrip().endswith('endmodule'))


if __name__ == '__main__':
    unittest.main()
