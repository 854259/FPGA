"""AMD-only frozen synthetic boundary audit for the existing prompt map parser."""
import argparse
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import sys
import time

EXTRA = [
    "Output y must equal the map result XOR p.",
    "Use a flip-flop on y.",
    "Hold y when p is zero.",
    "The output follows the table after two cycles.",
    "The table gives an intermediate function t; y is t OR p.",
    "Output y is delayed by one cycle.",
    "Output y must be negated.",
    "Output y is 1 only when q is 1, regardless of the map.",
    "Swap p and q before reading the table.",
    "Output y equals the opposite of each table entry.",
    "Output y is the complement of the map.",
    "Input p is active-low.",
]


def material(n, axis, column_order, reverse_rows, reverse_interface, extra=""):
    names = list("pqrs"[:n])
    nr = n // 2
    rows, columns = axis[:nr], axis[nr:]
    labels = [format(i, f"0{len(columns)}b") for i in range(2 ** len(columns))]
    if column_order == 1:
        labels = [format(i ^ (i >> 1), f"0{len(columns)}b") for i in range(2 ** len(columns))]
    elif column_order == 2:
        labels.reverse()
    row_labels = [format(i, f"0{len(rows)}b") for i in range(2 ** len(rows))]
    if reverse_rows:
        row_labels.reverse()
    interface = list(reversed(names)) if reverse_interface else names
    prefix = ("I would like you to implement a module named TopModule with the following\n"
              "interface. All input and output ports are one bit unless otherwise specified.\n\n")
    prefix += "\n".join(" - input " + name for name in interface) + "\n - output y\n\n"
    if extra:
        prefix += extra + "\n"
    prefix += "The module should implement the Karnaugh map below.\n\n"
    table = " " + "".join(columns) + "\n " + "".join(rows) + " " + " ".join(labels) + "\n"
    expected = {}
    for bits in itertools.product((0, 1), repeat=n):
        index = sum(bit << (n - 1 - i) for i, bit in enumerate(bits))
        expected[bits] = (0xA37D >> index) & 1
    for row in row_labels:
        values = []
        for col in labels:
            assignments = dict(zip(rows + columns, map(int, row + col)))
            values.append(str(expected[tuple(assignments[name] for name in names)]))
        table += row + " | " + " | ".join(values) + " |\n"
    return prefix + table, names, expected


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parser", required=True, type=Path)
    ap.add_argument("--parser-sha256", required=True)
    ap.add_argument("--resource-check", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    assert sys.platform == "linux"
    sys.dont_write_bytecode = True
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    assert sha(args.parser) == args.parser_sha256
    resource = json.loads(args.resource_check.read_text())
    assert resource["resource_idle"] is True
    assert sha(Path(resource["slot_lock_path"])) == resource["slot_lock_sha256"]
    module_spec = importlib.util.spec_from_file_location("frozen_map_parser", args.parser)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    tick = time.monotonic()
    rows = []
    for n in (2, 3, 4):
        for axis in itertools.permutations("pqrs"[:n]):
            for order, rev_rows, rev_interface in itertools.product(range(3), (False, True), (False, True)):
                prompt, names, expected = material(n, axis, order, rev_rows, rev_interface)
                got = module.parse(prompt)
                actual = {tuple(c["inputs"][name] for name in names): c["expected"]
                          for c in got.get("cases", [])}
                ok = got["status"] == "supported" and actual == expected
                rows.append(dict(kind="supported_axis_and_interface_permutation", n=n,
                    prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                    expected="exact_complete_table", actual_status=got["status"], passed=ok,
                    checks=got.get("checks"), reason=got.get("reason")))
        for extra in EXTRA:
            prompt, _, _ = material(n, tuple("pqrs"[:n]), 0, False, False, extra)
            got = module.parse(prompt)
            rows.append(dict(kind="additional_semantic_requirement", n=n, extra=extra,
                prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                expected="abstain", actual_status=got["status"],
                passed=got["status"] == "abstain", reason=got.get("reason")))
    assert sha(args.parser) == args.parser_sha256
    assert time.monotonic() - tick < 30
    args.out.mkdir(exist_ok=False, parents=True)
    (args.out / "PRIVATE_CASES.json").write_text(json.dumps(rows, indent=2) + "\n")
    summary = dict(complete=True, parser_sha256=args.parser_sha256,
        script_sha256=sha(Path(__file__)), tests=len(rows),
        supported_cases=sum(r["kind"].startswith("supported") for r in rows),
        semantic_abstention_cases=sum(r["kind"].startswith("additional") for r in rows),
        failures=sum(not r["passed"] for r in rows),
        false_accepts=sum(r["expected"] == "abstain" and r["actual_status"] == "supported" for r in rows),
        candidate_admitted=all(r["passed"] for r in rows),
        elapsed_s=time.monotonic()-tick, model_calls=0, eda_calls=0,
        independent_natural_tasks=0, full_batch_complete=False,
        scope="Constructed development grammar controls; not new natural holdout or RTL functional certification")
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
