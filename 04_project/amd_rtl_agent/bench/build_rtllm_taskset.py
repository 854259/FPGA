#!/usr/bin/env python3
"""Convert RTLLM v2.1 designs into this project's pinned task format.

Why this exists
---------------
The official judge needs a task directory shaped as

    prompt.txt  ref.sv  tb.sv  reference/solution.sv  task.json

where ``ref.sv`` defines ``RefModule``, ``reference/solution.sv`` defines the
submitted top name, and ``tb.sv`` instantiates both and prints
``Mismatches: N in M samples``.

RTLLM ships a natural-language description, a hand-written reference design and a
testbench written for Synopsys VCS. Its testbench instantiates a single DUT, uses
a weak pass banner instead of a reference comparison, and cannot report the
mismatch counts the judge parses. The description and the reference are the
valuable parts; the testbench is regenerated here as a dual-instantiation
comparison.

What it does NOT do
-------------------
It never looks at model output. The task set is meant to be frozen first and only
then used to measure generalisation, so nothing here may be tuned afterwards
against how a model performs.

Usage
-----
    python build_rtllm_taskset.py --rtllm <RTLLM checkout> --out <task set dir>
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

TOP_NAME = "TopModule"
REF_NAME = "RefModule"
PART = "xczu3eg-sbva484-1-e"
PERIOD_NS = 5

TYPE_WORDS = ("wire", "reg", "logic", "bit", "var", "signed", "unsigned")


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    return text


def split_top_level(text: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def parse_port_chunk(chunk: str):
    """Return (direction|None, name, width) for one port chunk."""
    chunk = " ".join(chunk.split())
    direction = None
    m = re.match(r"^(input|output|inout)\b(.*)$", chunk, re.S)
    if m:
        direction, chunk = m.group(1), m.group(2).strip()
    while True:
        m = re.match(r"^(?:" + "|".join(TYPE_WORDS) + r")\b\s*", chunk)
        if not m:
            break
        chunk = chunk[m.end():]
    width = None
    m = re.match(r"^\[([^\]]+)\]\s*", chunk)
    if m:
        width = m.group(1).strip()
        chunk = chunk[m.end():]
    m = re.match(r"^([A-Za-z_]\w*)", chunk)
    if not m:
        return None
    return direction, m.group(1), width


def parse_module(text: str, prefer: str | None):
    """Pick the module of interest and return (name, ports, body_ranges).

    Handles ANSI headers, non-ANSI headers with body declarations, and files that
    contain several modules (pick the one whose name best matches `prefer`).
    """
    clean = strip_comments(text)
    heads = list(re.finditer(r"\bmodule\s+([A-Za-z_]\w*)", clean))
    if not heads:
        return None

    def normalise(s):
        return re.sub(r"[^a-z0-9]", "", s.lower().lstrip("verified"))

    chosen = None
    if prefer:
        target = normalise(prefer)
        for h in heads:
            if normalise(h.group(1)) == target:
                chosen = h
                break
    if chosen is None:
        chosen = heads[0]

    name = chosen.group(1)
    tail = clean[chosen.end():]
    m = re.match(r"\s*(?:#\s*\(.*?\)\s*)?\((.*?)\)\s*;", tail, re.S)
    if m:
        header_ports = split_top_level(m.group(1))
    else:
        header_ports = []

    ports = []
    for chunk in header_ports:
        parsed = parse_port_chunk(chunk)
        if parsed:
            ports.append(parsed)

    # Non-ANSI: directions live in the module body. Collect every declaration.
    body = clean[chosen.end():]
    end = body.find("endmodule")
    body = body[:end] if end >= 0 else body
    body_decls = {}
    for stmt in body.split(";"):
        stmt = " ".join(stmt.split())
        m = re.match(r"^(input|output|inout)\b(.*)$", stmt, re.S)
        if not m:
            continue
        direction, rest = m.group(1), m.group(2).strip()
        # A single statement may declare several names: `input a, b, c`
        for piece in rest.split(","):
            piece = piece.strip()
            if not piece:
                continue
            while True:
                mm = re.match(r"^(?:" + "|".join(TYPE_WORDS) + r")\b\s*", piece)
                if not mm:
                    break
                piece = piece[mm.end():]
            width = None
            mm = re.match(r"^\[([^\]]+)\]\s*", piece)
            if mm:
                width = mm.group(1).strip()
                piece = piece[mm.end():]
            mm = re.match(r"^([A-Za-z_]\w*)", piece)
            if mm:
                body_decls[mm.group(1)] = (direction, mm.group(1), width)

    if any(p[0] is None for p in ports):
        fixed = []
        for direction, pname, width in ports:
            if direction is None and pname in body_decls:
                fixed.append(body_decls[pname])
            else:
                fixed.append((direction, pname, width))
        ports = fixed

    ports = [p for p in ports if p[0] in ("input", "output", "inout")]
    return name, ports


def rename_module(text: str, old: str, new: str) -> str:
    text = re.sub(r"(\bmodule\s+)" + re.escape(old) + r"\b", r"\1" + new, text, count=1)
    text = re.sub(r"(\bendmodule\b)", r"\1", text)  # no-op, keeps intent explicit
    return text


def find_testbench_ports(reference_text: str, module_name: str, ports):
    """Sanity gate: the design must have at least one input and one output."""
    inputs = [p for p in ports if p[0] == "input"]
    outputs = [p for p in ports if p[0] == "output"]
    return inputs, outputs


def clock_like(name: str) -> bool:
    """RTLLM names clocks inconsistently: clk, CLK, Clk, CLK_in, clk_a, wclk."""
    return re.search(r"(?i)clk|clock", name) is not None


def reset_like(name: str) -> bool:
    return re.search(r"(?i)rst|reset", name) is not None


def reset_active_low(name: str) -> bool:
    """rtl, RST and reset are active high; rst_n, arstn, brstn and resetn are low."""
    flat = re.sub(r"[^a-z0-9]", "", name.lower())
    return flat.endswith("n")


def gen_testbench(module_inputs, module_outputs, clk_names, rst_names):
    """Emit a dual-instantiation testbench with the judge's expected report line.

    Every clock-like input is driven from one clock and every reset-like input is
    driven together, because RTLLM mixes CLK / Clk / CLK_in / clk_a / wclk and
    RST / Rst / arstn / brstn. Driving all of them keeps the comparison fair: the
    candidate and the reference receive exactly the same stimulus.
    """
    L = []
    L.append("`timescale 1 ns/1 ps")
    L.append("module tb;")
    L.append("")
    L.append("    integer errors = 0;")
    L.append("    integer samples = 0;")
    for direction, name, width in module_inputs:
        rng = f"[{width}] " if width else ""
        L.append(f"    reg {rng}{name} = 0;")
    for direction, name, width in module_outputs:
        rng = f"[{width}] " if width else ""
        L.append(f"    wire {rng}{name};")
    L.append("")
    conns = [f"        .{p[1]}({p[1]})" for p in module_inputs + module_outputs]
    for mod, label in ((REF_NAME, "good"), (TOP_NAME, "dut")):
        L.append(f"    {mod} {label} (")
        L.append(",\n".join(conns))
        L.append("    );")
    L.append("")
    if clk_names:
        L.append("    always #2.5 begin")
        for c in clk_names:
            L.append(f"        {c} = ~{c};")
        L.append("    end   // 5 ns period, matches the 200 MHz target")
        L.append("")
    L.append("    task check;")
    L.append("        begin")
    L.append("            samples = samples + 1;")
    for direction, name, width in module_outputs:
        L.append(f"            if (dut.{name} !== good.{name}) begin")
        L.append(f'                if (errors == 0) $display("Hint: Output \'%s\' first mismatched at time %0t.", "{name}", $time);')
        L.append("                errors = errors + 1;")
        L.append("            end")
    L.append("        end")
    L.append("    endtask")
    L.append("")
    L.append("    initial begin")
    if rst_names:
        for i, r in enumerate(rst_names):
            active = "1'b0" if reset_active_low(r) else "1'b1"
            L.append(f"        {r} = {active};")
        if clk_names:
            L.append("        repeat (4) @(negedge clk);" if len(clk_names) == 1 and clk_names[0] == "clk"
                     else f"        repeat (4) @(negedge {clk_names[0]});")
        for r in rst_names:
            inactive = "1'b1" if reset_active_low(r) else "1'b0"
            L.append(f"        {r} = {inactive};")
        if clk_names:
            L.append(f"        @(negedge {clk_names[0]});" if len(clk_names) > 1 or clk_names[0] != "clk"
                     else "        @(negedge clk);")
    L.append("        repeat (200) begin")
    for direction, name, width in module_inputs:
        if clock_like(name) or name in rst_names:
            continue
        L.append(f"            {name} = $random;")
    if clk_names:
        first = clk_names[0]
        L.append(f"            @(negedge {first});")
        L.append("            check;")
    else:
        L.append("            #1 check;")
    L.append("        end")
    L.append('        $display("Mismatches: %1d in %1d samples", errors, samples);')
    L.append("        $finish;")
    L.append("    end")
    L.append("")
    L.append("endmodule")
    return "\n".join(L) + "\n"


def load_prompt(desc_path: Path, design_name: str) -> str:
    text = desc_path.read_text(encoding="utf-8", errors="replace")
    # The contract says the module name comes from the prompt; our skill emits TOP_NAME.
    text = re.sub(r"(Module name:\s*\n?\s*)" + re.escape(design_name), r"\1" + TOP_NAME, text)
    if TOP_NAME not in text:
        text = f"Module name: {TOP_NAME}\n\n" + text
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rtllm", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--include", nargs="*", default=None, help="only these design folder names")
    args = ap.parse_args()

    designs = sorted(p.parent for p in args.rtllm.rglob("design_description.txt"))
    if args.include:
        keep = set(args.include)
        designs = [d for d in designs if d.name in keep]

    args.out.mkdir(parents=True, exist_ok=True)
    built, skipped = [], []

    for d in designs:
        refs = sorted(d.glob("verified_*.v"))
        if not refs:
            skipped.append((d.name, "no verified_*.v"))
            continue
        ref_text = refs[0].read_text(encoding="utf-8", errors="replace")
        parsed = parse_module(ref_text, prefer=d.name)
        if not parsed:
            skipped.append((d.name, "module not parsed"))
            continue
        mod_name, ports = parsed
        inputs = [p for p in ports if p[0] == "input"]
        outputs = [p for p in ports if p[0] == "output"]
        if not inputs or not outputs:
            skipped.append((d.name, f"untestable ({len(inputs)} in / {len(outputs)} out)"))
            continue

        names = {p[1] for p in inputs}
        clk_names = sorted(n for n in names if clock_like(n))
        rst_names = sorted(n for n in names if reset_like(n))

        task_id = d.name
        tdir = args.out / task_id
        if tdir.exists():
            shutil.rmtree(tdir)
        (tdir / "reference").mkdir(parents=True)

        (tdir / "prompt.txt").write_text(load_prompt(d / "design_description.txt", mod_name), encoding="utf-8")
        (tdir / "ref.sv").write_text(rename_module(ref_text, mod_name, REF_NAME), encoding="utf-8")
        (tdir / "reference" / "solution.sv").write_text(rename_module(ref_text, mod_name, TOP_NAME), encoding="utf-8")
        (tdir / "tb.sv").write_text(
            gen_testbench(inputs, outputs, clk_names, rst_names), encoding="utf-8")
        (tdir / "task.json").write_text(json.dumps({
            "task_id": task_id,
            "top": TOP_NAME,
            "part": PART,
            "period_ns": PERIOD_NS,
            "reference_module": "ref.sv",
            "testbench": "tb.sv",
            "tb_top": "tb",
            "extra_files": [],
            "reference": "reference/solution.sv",
            "source": f"RTLLM v2.1 {d.relative_to(args.rtllm)}",
        }, indent=2) + "\n", encoding="utf-8")
        built.append((task_id, len(inputs), len(outputs), ",".join(clk_names) or "-",
                      ",".join(rst_names) or "-"))

    print(f"built {len(built)} tasks, skipped {len(skipped)}")
    print("\nskipped:")
    for name, why in skipped:
        print(f"  {name:<34} {why}")
    print("\nbuilt:")
    for t, ni, no, clk, rst in built:
        kind = "sequential" if clk != "-" else "combinational"
        print(f"  {t:<34} in={ni} out={no} {kind:<14} clk={clk:<12} rst={rst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
