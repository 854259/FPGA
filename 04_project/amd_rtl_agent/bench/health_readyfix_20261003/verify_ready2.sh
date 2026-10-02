#!/bin/bash
# 按真实包布局验证：<stage>/agent/runtime.py + <stage>/baseline.py + <stage>/upstream.json
K=/workspace/team/tasks/autodl-rtl-kit/project
S=/tmp/stage_readyfix

rm -rf $S; mkdir -p $S/agent
cp $K/submission/baseline.py $S/baseline.py
cp $K/submission/run_baseline.sh $S/run_baseline.sh
cp $K/submission/upstream.json $S/upstream.json
cp /tmp/runtime.readyfix.py $S/agent/runtime.py

echo "=== 布局 ==="
find $S -maxdepth 2 -type f | sed "s#$S#  <stage>#"

export PATH=/workspace/AMD/2026.1/Vivado/bin:$PATH
export LD_LIBRARY_PATH=/workspace/team/udev-stub
export XILINXD_LICENSE_FILE=/workspace/team/Xilinx.lic
export XILINX_VIVADO=/workspace/AMD/2026.1/Vivado
export LLM_BASE_URL=http://127.0.0.1:8000/v1
export MODEL_NAME=Qwen3.6-27B-Q4_K_M
export NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost

echo
echo "=== 逐项条件（在正确布局下）==="
python3 - <<'PYEOF'
import importlib.util, os
spec = importlib.util.spec_from_file_location("cand", "/tmp/stage_readyfix/agent/runtime.py")
m = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(m)
except SystemExit:
    pass

model = os.environ.get("MODEL_NAME", "")
print("  PKG                  : %s" % m.PKG)
try:
    ms = m.models()
    print("  1) model in models() : %s  (%s)" % (model in ms, ms))
except Exception as e:
    print("  1) model in models() : 异常 %s" % type(e).__name__)
try:
    print("  2) baseline_integrity: %s" % m.baseline_integrity())
except Exception as e:
    print("  2) baseline_integrity: 异常 %s" % type(e).__name__)
xv = m.vivado_tool("xvlog")
print("  3) vivado_tool(xvlog): %s" % ("found" if xv else "None"))
print("  4) vivado_version    : %r" % m.vivado_version(m.vivado_tool("vivado")))
print("  5) vram_gb()         : %r GB" % m.vram_gb())
print()
for prof in ("development", "submission"):
    os.environ["RTL_PROFILE"] = prof
    print("  RTL_PROFILE=%-12s -> %s" % (prof, m.health()))
PYEOF
