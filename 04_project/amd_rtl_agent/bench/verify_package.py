#!/usr/bin/env python3
"""交付包一致性核对（只读）。

用途：在同步前后核对
  1) manifest.json 声明的哈希 vs 提交包内实际文件；
  2) 提交包内各文件哈希（供发布记录使用）；
  3) 可选：与另一份目录快照逐文件比对。

不修改任何文件。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tree(root: pathlib.Path) -> dict[str, str]:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            out[str(p.relative_to(root)).replace("\\", "/")] = sha(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True, help="提交包根目录")
    ap.add_argument("--against", default=None, help="对照目录（可选）")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()

    root = pathlib.Path(args.root)
    if not root.is_dir():
        print("找不到目录:", root)
        return 2
    files = tree(root)
    problems: list[str] = []

    print("=" * 74)
    print("交付包一致性核对  %s" % root)
    print("=" * 74)
    print("文件数 %d" % len(files))

    man_p = root / "manifest.json"
    if man_p.is_file():
        man = json.loads(man_p.read_text(encoding="utf-8"))
        print()
        print("--- manifest.json 声明 vs 实际 ---")
        claims = []
        rt = man.get("runtime") or {}
        if rt.get("path") and rt.get("sha256"):
            claims.append((rt["path"], rt["sha256"], "runtime.path"))
        sv = man.get("serving") or {}
        if sv.get("start_command") and sv.get("sha256"):
            claims.append((sv["start_command"].lstrip("./"), sv["sha256"], "serving.start_command"))
        supervisor = sv.get("supervisor")
        supervisor_sha = sv.get("supervisor_sha256")
        if not isinstance(supervisor, str) or not supervisor:
            problems.append("manifest 缺少 serving.supervisor 启动入口路径")
        elif not isinstance(supervisor_sha, str) or not supervisor_sha:
            problems.append("manifest 缺少 serving.supervisor_sha256 启动入口哈希")
        else:
            # Only remove an explicit current-directory prefix. lstrip('./')
            # would turn ../serve/serve_all.sh into a different, valid path.
            rel = supervisor[2:] if supervisor.startswith("./") else supervisor
            claims.append((rel, supervisor_sha, "serving.supervisor"))
        for rel, want, where in claims:
            got = files.get(rel)
            if got is None:
                print("  MISSING  %-30s (%s)" % (rel, where))
                problems.append("manifest 指向的文件不存在: %s" % rel)
            elif got == want:
                print("  OK       %-30s %s" % (rel, got[:16]))
            else:
                print("  ★STALE   %-30s 实际=%s 声明=%s (%s)"
                      % (rel, got[:16], want[:16], where))
                problems.append("manifest 声明的 %s 哈希与实际不符 (声明 %s, 实际 %s)"
                                % (rel, want[:16], got[:16]))
        # 无哈希声明的关键文件：只提示
        for rel, where in (("serve/llama.sh", "serving"),
                           ("baseline.py", "baseline"),
                           ("run.sh", "endpoints.solve"),
                           ("run_baseline.sh", "endpoints.baseline")):
            if rel in files and rel not in [c[0] for c in claims]:
                print("  NOHASH   %-30s %s（manifest 未声明哈希）" % (rel, files[rel][:16]))
    else:
        problems.append("提交包缺少 manifest.json，无法核对声明")

    print()
    print("--- 提交包全量哈希 ---")
    for rel, h in files.items():
        print("  %s  %s" % (h[:16], rel))

    if args.against:
        other = pathlib.Path(args.against)
        if other.is_dir():
            other_files = tree(other)
            print()
            print("--- 与对照目录比对  %s ---" % other)
            for rel in sorted(set(files) | set(other_files)):
                a, b = files.get(rel), other_files.get(rel)
                if a == b:
                    print("  OK     %-40s %s" % (rel, (a or "-")[:16]))
                else:
                    print("  ★DIFF  %-40s 本=%s 对照=%s" % (rel, (a or "-")[:16], (b or "-")[:16]))
                    problems.append("与对照目录不一致: %s" % rel)
        else:
            problems.append("找不到指定的对照目录: %s" % other)

    if args.json_out:
        pathlib.Path(args.json_out).write_text(json.dumps(
            {"root": str(root), "files": files, "problems": problems},
            indent=2, ensure_ascii=False), encoding="utf-8")
        print()
        print("明细已写入", args.json_out)

    print()
    if problems:
        print("★ 发现 %d 处不一致：" % len(problems))
        for p in problems:
            print("   -", p)
        return 1
    print("核对通过：manifest 声明与实际内容一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
