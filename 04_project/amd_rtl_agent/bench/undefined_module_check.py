#!/usr/bin/env python3
"""纯文本检测"实例化了未定义子模块"，零工具成本。

为什么做这个
------------
`xelab` 能在细化阶段抓到 "Module <X> not found"，但每题要 1.12 秒。若同一判断
用文本分析就能做到，成本近乎为零——而"代价项"正是按墙钟计量的，秒级成本有实际
分数含义。

关键风险是**误报**：把一个正常设计误判成"缺子模块"，会白白触发一次修复生成
（约 15 秒），比 xelab 还贵。所以本脚本的输出必须与 xelab 的实测结果逐题比对，
不能只看它抓到了几个。

用法
----
    undefined_module_check.py <解答文件或目录>... [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

# Verilog/SystemVerilog 内建原语与常见门级单元，不算"未定义子模块"
PRIMITIVES = {
    "and", "nand", "or", "nor", "xor", "xnor", "not", "buf",
    "bufif0", "bufif1", "notif0", "notif1", "nmos", "pmos", "cmos",
    "rnmos", "rpmos", "rcmos", "tran", "tranif0", "tranif1", "rtran",
    "rtranif0", "rtranif1", "pullup", "pulldown",
}

# 关键字：出现在实例化位置时不是模块名
KEYWORDS = {
    "module", "endmodule", "input", "output", "inout", "wire", "reg", "logic",
    "assign", "always", "initial", "begin", "end", "if", "else", "case",
    "endcase", "casez", "casex", "for", "while", "repeat", "forever", "function",
    "endfunction", "task", "endtask", "generate", "endgenerate", "genvar",
    "parameter", "localparam", "defparam", "posedge", "negedge", "integer",
    "real", "time", "signed", "unsigned", "default", "return", "break",
    "continue", "typedef", "struct", "enum", "packed", "unpacked", "static",
    "automatic", "localparam", "specify", "endspecify", "primitive", "table",
    "endtable", "supply0", "supply1", "tri", "triand", "trior", "wand", "wor",
    "byte", "shortint", "int", "longint", "bit", "string", "void", "assert",
    "assume", "cover", "property", "endproperty", "sequence", "endsequence",
    "interface", "endinterface", "package", "endpackage", "import", "export",
    "class", "endclass", "new", "this", "super", "extends", "virtual", "pure",
}

# 门级原语的带强度/延迟写法：and #(1) g1 (...)
RE_MODULE_DECL = re.compile(r"^\s*module\s+([A-Za-z_]\w*)", re.M)

# 实例化的判定必须靠【具名端口映射】。第一版只匹配 `Name inst (`，结果把
# `for (i = 0; ...)` 里的循环变量当成了模块名 —— 在 VerilogEval 上误报 69/156
# （xelab 真值 1），在 RTLLM 上误报 38/44（真值 5）。真实实例化几乎总写成
# `.port(signal)`，循环与条件语句不会，用这个特征才能区分开。
RE_INSTANTIATION = re.compile(
    r"(?m)^[ \t]*([A-Za-z_]\w*)\s*(?:#\s*\([^;]*?\)\s*)?([A-Za-z_]\w*)\s*"
    r"(?:\[[^\]]*\]\s*)?\(([^;]*?)\)\s*;",
    re.S)


def _has_named_port_map(ports: str) -> bool:
    """具名端口映射：.clk(clk) 这种。位置映射（inst(a, b)）极少出现在生成代码里。"""
    return re.search(r"\.\s*[A-Za-z_]\w*\s*\(", ports) is not None


def strip_comments_and_strings(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    text = re.sub(r'"(?:[^"\\]|\\.)*"', '""', text)
    return text


def analyse(path: pathlib.Path):
    raw = path.read_text(encoding="utf-8", errors="replace")
    text = strip_comments_and_strings(raw)

    defined = set(RE_MODULE_DECL.findall(text))

    instantiated = set()
    for mod, inst, ports in RE_INSTANTIATION.findall(text):
        if mod in KEYWORDS or mod in PRIMITIVES:
            continue
        # 必须具名端口映射，否则 `for (i = ...)` 这类会被误判成实例化
        if not _has_named_port_map(ports):
            continue
        instantiated.add(mod)

    missing = sorted(m for m in instantiated if m not in defined)
    return dict(path=str(path), defined=sorted(defined),
                instantiated=sorted(instantiated), missing=missing)


def collect(targets):
    files = []
    for t in targets:
        p = pathlib.Path(t)
        if p.is_dir():
            files.extend(sorted(p.rglob("*.v")) + sorted(p.rglob("*.sv")))
        elif p.is_file():
            files.append(p)
    return files


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("targets", nargs="+")
    ap.add_argument("--json", type=pathlib.Path, default=None)
    args = ap.parse_args()

    files = collect(args.targets)
    results = [analyse(f) for f in files]

    flagged = [r for r in results if r["missing"]]
    print("文件数        : %d" % len(results))
    print("报『缺子模块』: %d" % len(flagged))
    print()
    for r in flagged:
        print("  %s" % r["path"])
        print("     已定义  : %s" % ", ".join(r["defined"]) or "(无)")
        print("     实例化  : %s" % ", ".join(r["instantiated"]))
        print("     判为缺失: %s" % ", ".join(r["missing"]))
    if args.json:
        args.json.write_text(json.dumps(results, indent=2, ensure_ascii=False),
                             encoding="utf-8")
        print("\n已写出:", args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
