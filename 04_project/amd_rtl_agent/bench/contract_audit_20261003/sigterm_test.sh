#!/bin/bash
# 契约合规测试：收到 SIGTERM 后是否在 10 秒内退出（契约第 287 行）
#
# 契约原文：由赛事方的测试脚本强制，到点发 SIGTERM。
#           收到后须在 10 秒内退出，否则 SIGKILL，该题按 L0 计。
#
# 同时验证：退出后不能留下孤儿 worker/vivado 进程（否则会污染后续样本）
set -u
K=/workspace/team/tasks/autodl-rtl-kit/project
O=/workspace/team/runs/fpga_owner/sigterm_test_20261003
rm -rf "$O"; mkdir -p "$O/scratch"

export PATH=/workspace/AMD/2026.1/Vivado/bin:$PATH
export LD_LIBRARY_PATH=/workspace/team/udev-stub
export XILINXD_LICENSE_FILE=/workspace/team/Xilinx.lic
export XILINX_VIVADO=/workspace/AMD/2026.1/Vivado
export LLM_BASE_URL=http://127.0.0.1:8000/v1 MODEL_NAME=Qwen3.6-27B-Q4_K_M
export RTL_PROFILE=development RTL_REPAIRS=1 RTL_MAX_TOKENS=8192 RTL_TEMPERATURE=0
export NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost
export EDA_TMP=$O/scratch SELFTEST_TMP=$O/scratch

count_orphans() {
  ps -eo pid,ppid,args 2>/dev/null | grep -E "runtime.py worker|judge.py|xsim|xvlog|vivado" \
    | grep -v grep | wc -l
}

echo "=== 基线：测试前有无相关进程 ==="
echo "  相关进程数: $(count_orphans)"

TASKS="Prob001_zero Prob050_kmap1 Prob147_circuit10"
for T in $TASKS; do
  echo
  echo "######## $T ########"
  D="$O/$T"; mkdir -p "$D"
  BEFORE=$(count_orphans)

  # 后台启动 agent
  python3 -B "$K/submission/agent/runtime.py" run "$K/bench/tasks_veval/$T" "$D" \
    > "$D/stdout.log" 2>&1 &
  PID=$!
  echo "  启动 PID=$PID"

  # 等到确实进入工作状态（出现 worker 子进程）再发信号
  WAITED=0
  for i in $(seq 1 40); do
    sleep 0.5; WAITED=$((WAITED+1))
    if [ "$(count_orphans)" -gt "$BEFORE" ]; then break; fi
  done
  echo "  已运行约 $(python3 -c "print('%.1f' % ($WAITED*0.5))")s，相关进程 $(count_orphans)"

  # 发 SIGTERM 并计时
  S=$(date +%s.%N)
  kill -TERM $PID 2>/dev/null
  for i in $(seq 1 200); do
    kill -0 $PID 2>/dev/null || break
    sleep 0.1
  done
  E=$(date +%s.%N)
  D_SEC=$(python3 -c "print('%.2f' % ($E-$S))")

  if kill -0 $PID 2>/dev/null; then
    echo "  ✗ 10 秒内未退出（已等 ${D_SEC}s）"
    kill -9 $PID 2>/dev/null
  else
    if python3 -c "import sys; sys.exit(0 if $D_SEC <= 10 else 1)"; then
      echo "  ✓ 退出耗时 ${D_SEC}s  （契约要求 <= 10s）"
    else
      echo "  ✗ 退出耗时 ${D_SEC}s  超过 10s"
    fi
  fi

  # 是否产出了文件
  echo -n "  产出: "
  [ -f "$D/solution.v" ] && echo -n "solution.v($(wc -c < "$D/solution.v")B) " || echo -n "无 solution.v "
  [ -f "$D/trace.jsonl" ] && echo   "trace.jsonl($(wc -c < "$D/trace.jsonl")B)" || echo   "无 trace.jsonl"

  # 孤儿进程
  sleep 2
  AFTER=$(count_orphans)
  echo -n "  退出后相关进程数: $AFTER  "
  if [ "$AFTER" -le "$BEFORE" ]; then echo "✓ 无孤儿"; else
    echo "✗ 有孤儿残留："
    ps -eo pid,ppid,args | grep -E "runtime.py worker|judge.py|xsim|vivado" | grep -v grep | head -5 | sed 's/^/      /'
  fi
done

echo
echo "=== 总结 ==="
echo "  契约要求：SIGTERM 后 10 秒内退出，否则 SIGKILL 且该题按 L0"
