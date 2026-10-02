"""Regression tests for the text-based undefined-submodule check.

Why this check exists
---------------------
A hierarchical design that instantiates a module it never defines passes `xvlog`,
because analysis does not resolve module instantiation. It only fails at elaboration,
which the judge runs and the agent does not, so the agent submits it believing it
succeeded and the task scores L0.

Running `xelab` would catch it at about 1.1 s per task on every task. A text check
costs nothing and fires only when something is actually wrong. Measured effect on the
four tasks it fires on: one moved from L0 to L3.

The false-positive case below is the one that matters most: the first version matched
any `Name inst (` and therefore read `for (i = 0; ...)` as an instantiation of module
`i`, producing 69 false positives out of 156 on VerilogEval. Validating against xelab
ground truth is what exposed it.
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


runtime = load('contract_runtime_submodules', ROOT / 'submission/agent/runtime.py')


class UndefinedSubmoduleTests(unittest.TestCase):

    def test_self_contained_module_is_clean(self):
        code = """
module TopModule (input a, output y);
    assign y = ~a;
endmodule
"""
        self.assertEqual(runtime.undefined_submodules(code), [])

    def test_missing_submodule_is_reported(self):
        code = """
module TopModule (input [7:0] a, output [7:0] y);
    adder_8bit u0 (.a(a), .y(y));
endmodule
"""
        self.assertEqual(runtime.undefined_submodules(code), ['adder_8bit'])

    def test_locally_defined_submodule_is_clean(self):
        code = """
module TopModule (input [7:0] a, output [7:0] y);
    helper u0 (.a(a), .y(y));
endmodule

module helper (input [7:0] a, output [7:0] y);
    assign y = a;
endmodule
"""
        self.assertEqual(runtime.undefined_submodules(code), [])

    def test_for_loop_variable_is_not_an_instantiation(self):
        """The regression that produced 69 false positives out of 156."""
        code = """
module TopModule (input clk, output reg [3:0] q);
    integer i;
    always @(posedge clk) begin
        for (i = 0; i < 4; i = i + 1) begin
            q <= i;
        end
    end
endmodule
"""
        self.assertEqual(runtime.undefined_submodules(code), [])

    def test_gate_primitives_are_not_modules(self):
        code = """
module TopModule (input a, b, output y);
    wire n;
    and g1 (n, a, b);
    not g2 (y, n);
endmodule
"""
        self.assertEqual(runtime.undefined_submodules(code), [])

    def test_positional_port_map_is_ignored_by_design(self):
        """Positional connections are not treated as instantiations.

        Accepted limitation: a design using positional port maps on an undefined module
        is not flagged here. Generated candidates almost always use named maps, and the
        narrower rule is what keeps the false-positive count at zero.
        """
        code = """
module TopModule (input a, output y);
    mystery u0 (a, y);
endmodule
"""
        self.assertEqual(runtime.undefined_submodules(code), [])

    def test_comments_do_not_create_instantiations(self):
        code = """
module TopModule (input a, output y);
    // adder_8bit u0 (.a(a), .y(y));
    /* mult_8bit u1 (.a(a), .y(y)); */
    assign y = a;
endmodule
"""
        self.assertEqual(runtime.undefined_submodules(code), [])

    def test_multiple_missing_modules_are_listed_once(self):
        code = """
module TopModule (input [7:0] a, output [7:0] y);
    blk_a u0 (.a(a), .y(w));
    blk_b u1 (.a(w), .y(y));
    blk_a u2 (.a(a), .y(w2));
endmodule
"""
        self.assertEqual(runtime.undefined_submodules(code), ['blk_a', 'blk_b'])


if __name__ == '__main__':
    unittest.main()
