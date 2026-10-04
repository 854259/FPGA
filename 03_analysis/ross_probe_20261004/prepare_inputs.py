"""Freeze a bounded Vivado experiment; does not install or invoke ROSS MCP."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    sources = {
        "official_faults": (
            (ROOT / "upstream/examples/rtl-lint/multi-violation/input/src/lint_violation_top.v").read_bytes(),
            "lint_violation_top",
            "AMD multi-violation source, unchanged; target part adapted to the competition part",
            "diagnostic_positive",
        ),
        "old_faults": (
            b"""module TopModule (
 input wire clk, input wire [3:0] sel, input wire [7:0] a,
 output reg [7:0] y, output wire [7:0] undriven_out, output reg [7:0] ovf
);
always @(*) begin if (sel == 1) y = a; end
always @(posedge clk) begin ovf <= a + 8'hFF; end
endmodule
""",
            "TopModule", "Reconstructs the three defect mechanisms in the archived old control", "diagnostic_positive",
        ),
        "clean_guard": (
            b"""module TopModule(input wire [7:0] a,b, input wire sel,
 output wire [7:0] y, output wire [7:0] bitxor);
assign y = sel ? a : b;
assign bitxor = a ^ b;
endmodule
""",
            "TopModule", "Fully assigned combinational mux and XOR; no expected lint violations", "diagnostic_negative",
        ),
        "modulo_guard": (
            b"""module TopModule(input wire [7:0] a,b, output wire [7:0] y);
// The specification requires modulo-256 addition and this fixed 8-bit interface.
assign y = a + b;
endmodule
""",
            "TopModule", "Intended modulo-256 arithmetic: an overflow warning is not permission to widen the port", "semantic_guard",
        ),
    }
    manifest = {}
    for name, (data, top, description, role) in sources.items():
        target = ROOT / "inputs" / name / "candidate.sv"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != data:
            raise RuntimeError("refusing to change previously frozen input: " + name)
        target.write_bytes(data)
        manifest[name] = dict(file=str(target.relative_to(ROOT)).replace("\\", "/"),
                              top=top, sha256=sha(data), bytes=len(data), description=description, role=role)
    spec = dict(schema="ross_vivado_lint_probe_v1", date="2026-10-04", status="frozen_before_eda",
                upstream_commit="2cdc9eef1b6b5b17fa45f5e4d468e5483a1c92de",
                scope="Underlying Vivado command and report verification, not ROSS MCP integration",
                part="xczu3eg-sbva484-1-e", model_calls=0, lint_runs=8, synthesis_runs=1,
                timeout_s_per_run=90, configurations=["archived_default", "official_csv_option"],
                csv_option='set_param synth.elaboration.rodinMoreOptions "rt::set_parameter linterCsvFile true"',
                inputs=manifest,
                acceptance={"tool_validity": "All commands finish without tool/environment errors; reports and inputs are traceable",
                            "lint_engine": "At least the AMD fault control must produce a nonzero linter count with a consistent parse; clean guard should remain zero",
                            "zero_count": "Zero on diagnostic-positive controls means the diagnostic mechanism is unverified, not that the design is correct",
                            "semantic_guard": "No code is changed; warnings on specified modulo arithmetic do not establish a functional bug"},
                limitations=["No model repair or gain measurement", "No official MCP binary installed or called",
                             "The sample README's exact expected count uses a different device; we report differences rather than assert equivalence",
                             "No hidden reference or official testbench provided to any model",
                             "Protected package, baseline, official judge and shared model remain unchanged"])
    (ROOT / "RUN_SPEC.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"inputs": len(manifest), "lint_runs": spec["lint_runs"], "model_calls": 0}))


if __name__ == "__main__":
    main()
