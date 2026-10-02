#!/bin/bash
# CLI 路径冒烟：确认 health 修复没有影响实际评测路径
set -u
K=/workspace/team/tasks/autodl-rtl-kit/project
O=/workspace/team/runs/fpga_owner/cli_smoke_after_readyfix
rm -rf "$O"; mkdir -p "$O/scratch" "$O/results"

export PATH=/workspace/AMD/2026.1/Vivado/bin:$PATH
export LD_LIBRARY_PATH=/workspace/team/udev-stub
export XILINXD_LICENSE_FILE=/workspace/team/Xilinx.lic
export XILINX_VIVADO=/workspace/AMD/2026.1/Vivado
export LLM_BASE_URL=http://127.0.0.1:8000/v1 MODEL_NAME=Qwen3.6-27B_Q4_K_M
export MODEL_NAME=Qwen3.6-27B-Q4_K_M
export RTL_PROFILE=development RTL_REPAIRS=1 RTL_MAX_TOKENS=8192 RTL_TEMPERATURE=0
export NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost
export EDA_TMP=$O/scratch SELFTEST_TMP=$O/scratch
export PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1

echo "=== 生效 runtime ==="
sha256sum "$K/submission/agent/runtime.py" | cut -c1-16
echo "  期望 cea6479c6364fbfc"

echo
echo "=== CLI 跑 3 道题（agent 模式），走 official_eval ==="
mkdir -p "$O/tasks"
for t in Prob001_zero Prob050_kmap1 Prob058_alwaysblock2; do
  cp -r "$K/bench/tasks_veval/$t" "$O/tasks/"
done
echo "  题目: $(ls -1 $O/tasks | tr '\n' ' ')"

cd "$K"
python3 -B official_eval.py --tasks "$O/tasks" --out "$O/out" --samples 1 --deadline 300 2>&1 | tail -12

echo
echo "=== 结果 ==="
if [ -f "$O/out/graded_summary.json" ]; then
  python3 -c "
import json
d = json.load(open('$O/out/graded_summary.json'))
for m, s in d['modes'].items():
    print('  %-9s set=%.4f levels=%s tool_errors=%d' % (m, s['set_score'], s['level_counts'], s['tool_errors']))
"
  echo
  echo "  逐题（agent）："
  for f in "$O/out/results/agent."*.json; do
    python3 -c "
import json,os
d=json.load(open('$f'))
print('    %-30s L%s' % (d['task_id'], d['level']))
"
  done
else
  echo "  ✗ 无 graded_summary"
fi

echo
echo "=== 与冻结预期对照 ==="
echo "  Prob001_zero    期望 L3"
echo "  Prob050_kmap1   期望 L1"
echo "  Prob058_alwaysblock2 期望 L3（本轮声明补丁修好的那题）"
