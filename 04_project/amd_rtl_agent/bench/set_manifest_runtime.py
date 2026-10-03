#!/usr/bin/env python3
"""把 manifest.json 的 runtime 哈希指向实际发布版本。

用法：
    python3 set_manifest_runtime.py <submission_dir> <adopted|rollback>

adopted  -> manifest.runtime.sha256 取 agent/runtime.py 的实际哈希（发布候选）
rollback -> 实测 agent/runtime.py 必须等于固定稳定版哈希，才允许写入；任意其它版本均拒绝

不猜内容：只改 runtime.sha256 一个字段，其余字段原样保留（保持键顺序与缩进）。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

STABLE_RUNTIME = "cea6479c6364fbfce55ca8129e8cfd7bb4b9afd3b2a4c7ae2e3cd381af2968b1"
CANDIDATE_RUNTIME = "728499f4699ed2214d5f4355ce0b5c58dc7504d3e177d40f914cf8e7b6f5ea97"


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[2] not in ("adopted", "rollback"):
        print(__doc__)
        return 2
    root = pathlib.Path(sys.argv[1])
    mode = sys.argv[2]
    rt = root / "agent" / "runtime.py"
    man_p = root / "manifest.json"
    if not rt.is_file() or not man_p.is_file():
        print("缺少 agent/runtime.py 或 manifest.json")
        return 2

    actual = sha(rt)
    man = json.loads(man_p.read_text(encoding="utf-8"))
    declared = (man.get("runtime") or {}).get("sha256")

    print("模式: %s" % mode)
    print("  实际 agent/runtime.py : %s" % actual[:16])
    print("  manifest 原声明       : %s" % (declared or "(无)")[:16])

    if mode == "rollback":
        if actual != STABLE_RUNTIME:
            print("★ 现场 runtime 不是预期稳定版，回滚未完成；拒绝改 manifest")
            print("  期望稳定版: %s" % STABLE_RUNTIME)
            print("  实际版本  : %s" % actual)
            return 1
        want = STABLE_RUNTIME
    else:
        want = actual

    if declared == want:
        print("  已是目标值，无需修改")
        return 0

    man.setdefault("runtime", {})
    man["runtime"]["sha256"] = want
    if "path" not in man["runtime"]:
        man["runtime"]["path"] = "agent/runtime.py"
    man_p.write_text(json.dumps(man, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("  已更新 manifest.runtime.sha256 -> %s" % want[:16])
    print("  新 manifest 哈希: %s" % sha(man_p)[:16])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
