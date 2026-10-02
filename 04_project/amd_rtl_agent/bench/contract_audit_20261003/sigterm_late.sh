#!/bin/bash
# SIGTERM 补测：在 EDA 工具真正跑起来之后再中断（更接近契约里的截止时刻）
set -u
K=/workspace/team/tasks/autodl-rtl-kit/project
O=/workspace/team/runs/fpga_owner/sigterm_late_20261003
rm -rf "$O"; mkdir -p "$O/scratch"

export PATH=/workspace/AMD/2026.1/Vivado/bin:$PATH
export LD_LIBRARY_PATH=/workspace/team/udev-stub
export XILINXD_LICENSE_FILE=/workspace/team/Xilinx.lic
export XILINX_VIVADO=/workspace/AMD/2026.1/Vivado
export LLM_BASE_URL=http://127.0.0.1:8000/v1 MODEL_NAME=Qwen3.6-27B-Q4_K_M
export RTL_PROFILE=development RTL_REPAIRS=1 RTL_MAX_TOKENS=8192 RTL_TEMPERATURE=0
export NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost
export EDA_TMP=$O/scratch SELFTEST_TMP=$O/scratch

related() {
  ps -eo pid,ppid,args 2>/dev/null | grep -E "runtime.py worker|judge.py|veval-judge|xsim|xvlog|xelab|vivado" \
    | grep -v grep | wc -l
}

echo "=== 基线相关进程: $(related) ==="

# 用一道会真正调用 Vivado 的题，等到 EDA 进程出现再中断
T=Prob001_zero
D="$O/$T"; mkdir -p "$D"
python3 -B "$K/submission/agent/runtime.py" run "$K/bench/tasks_veval/$T" "$D" > "$D/stdout.log" 2>&1 &
PID=$!
echo "  启动 PID=$PID"

# 等到出现 xvlog/vivado 之类的 EDA 子进程
FOUND=0
for i in $(seq 1 120); do
  sleep 0.5
  if ps -eo args 2>/dev/null | grep -qE "xvlog|xelab|xsim|vivado"; then FOUND=1; break; fi
done
echo "  EDA 进程出现: $FOUND  （等待 $(python3 -c "print('%.1f' % ($i*0.5))")s）"

if [ "$FOUND" = 1 ]; then
  echo "  中断前 EDA 进程:"
  ps -eo pid,ppid,etime,args | grep -E "xvlog|xelab|xsim|vivado" | grep -v grep | head -3 | cut -c1-110 | sed 's/^/      /'
  # 再跑一会儿，确保是"深处"中断
  sleep 2
  echo "  相关进程总数: $(related)"
else
  echo "  （未捕获到 EDA 进程，仍按当前状态中断）"
fi

S=$(date +%s.%N)
kill -TERM $PID 2>/dev/null
for i in $(seq 1 300); do kill -0 $PID 2>/dev/null || break; sleep 0.1; done
E=$(date +%s.%N)
DS=$(python3 -c "print('%.2f' % ($E-$S))")

if kill -0 $PID 2>/dev/null; then
  echo "  ✗ 30 秒内未退出"; kill -9 $PID 2>/dev/null
else
  python3 -c "import sys; sys.exit(0 if $DS <= 10 else 1)" \
    && echo "  ✓ 退出耗时 ${DS}s  （契约要求 <= 10s）" \
    || echo "  ✗ 退出耗时 ${DS}s  超过 10s"
fi

echo
echo "=== 退出后残留（关键：EDA 子进程必须一起走）==="
for i in 1 2 3 4 5; do
  N=$(related)
  [ "$N" -eq 0 ] && break
  sleep 1
done
N=$(related)
if [ "$N" -eq 0 ]; then
  echo "  ✓ 相关进程数 0，无孤儿"
else
  echo "  ✗ 仍有 $N 个相关进程："
  ps -eo pid,ppid,etime,args | grep -E "runtime.py worker|judge.py|xvlog|xelab|xsim|vivado" | grep -v grep | head -8 | cut -c1-115 | sed 's/^/      /'
fi

echo
echo "=== 产出 ==="
ls -la "$D" | sed 's/^/  /'
