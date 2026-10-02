#!/usr/bin/env bash
# 一键起服务 + 守护，保证比赛期间"一直不退出，守着一个端口"（契约 ①）。
#
# 为什么需要这个
# --------------
# 2026-10-03 排查发现：实例上【没有任何守护机制】——0 个 systemd 单元、0 条 cron、
# 没有 watchdog。llama-server 是手动 nohup 起来的，agent 的 HTTP 服务当时根本没在跑。
#
# 契约第 120 行写明：任何失败一律按 L0，不重试。也就是说，服务在比赛途中挂掉之后
# 的每一个样本都会是 0 分。这是尾部风险，用一个循环就能消掉。
#
# 用法
# ----
#   nohup bash serve_all.sh > /workspace/team/serve_all.log 2>&1 &
#
# 环境变量：
#   FPGACHINA_TOKEN  必填，契约要求的 Bearer 令牌
#   AGENT_PORT       默认 7860（契约规定的投题端口）
#   MODEL_PORT       默认 8000（仅回环，不对外）
#   CHECK_INTERVAL   健康检查间隔秒数，默认 30
set -uo pipefail

KIT="${KIT:-/workspace/team/tasks/autodl-rtl-kit/project}"
AGENT_PORT="${AGENT_PORT:-7860}"
MODEL_PORT="${MODEL_PORT:-8000}"
CHECK_INTERVAL="${CHECK_INTERVAL:-30}"
MODEL_PATH="${MODEL_PATH:-/workspace/team/models/Qwen3.6-27B-Q4_K_M.gguf}"
LLAMA_BIN="${LLAMA_BIN:-/workspace/team/tools/llama-build/bin/llama-server}"
LOG_DIR="${LOG_DIR:-/workspace/team/serve_logs}"
mkdir -p "$LOG_DIR"

if [ -z "${FPGACHINA_TOKEN:-}" ]; then
  echo "FPGACHINA_TOKEN is required" >&2
  exit 1
fi

export PATH="/workspace/AMD/2026.1/Vivado/bin:${PATH}"
export LD_LIBRARY_PATH="/workspace/team/udev-stub${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export XILINXD_LICENSE_FILE="${XILINXD_LICENSE_FILE:-/workspace/team/Xilinx.lic}"
export XILINX_VIVADO="${XILINX_VIVADO:-/workspace/AMD/2026.1/Vivado}"
export LLM_BASE_URL="http://127.0.0.1:${MODEL_PORT}/v1"
export MODEL_NAME="${MODEL_NAME:-Qwen3.6-27B-Q4_K_M}"
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"
export RTL_PROFILE="${RTL_PROFILE:-submission}"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUTF8=1

ts() { date -u +'%Y-%m-%dT%H:%M:%SZ'; }
say() { echo "[$(ts)] $*"; }

model_up()  { curl -s -o /dev/null -m 5 "http://127.0.0.1:${MODEL_PORT}/v1/models"; }
agent_up()  { curl -s -o /dev/null -m 5 -H "Authorization: Bearer ${FPGACHINA_TOKEN}" \
                "http://127.0.0.1:${AGENT_PORT}/v1/health"; }

start_model() {
  say "启动 llama-server（$MODEL_PATH）"
  nohup "$LLAMA_BIN" -m "$MODEL_PATH" --alias "$MODEL_NAME" \
    --host 127.0.0.1 --port "$MODEL_PORT" \
    -ngl "${MODEL_NGL:-99}" -c "${MODEL_CTX:-16384}" -np 1 \
    -t "${MODEL_THREADS:-8}" --reasoning off \
    >> "$LOG_DIR/llama-server-$(date -u +%Y%m%d).log" 2>&1 &
  echo $! > "$LOG_DIR/llama-server.pid"
  # 模型在 page cache 里时约 5 秒就绪；给足 180 秒
  for _ in $(seq 1 90); do model_up && { say "模型就绪"; return 0; }; sleep 2; done
  say "✗ 模型 180 秒内未就绪"
  return 1
}

start_agent() {
  say "启动 agent HTTP 服务（端口 $AGENT_PORT）"
  ( cd "$KIT" && nohup python3 -B submission/agent/runtime.py serve --port "$AGENT_PORT" \
      >> "$LOG_DIR/agent-serve-$(date -u +%Y%m%d).log" 2>&1 & echo $! > "$LOG_DIR/agent-serve.pid" )
  for _ in $(seq 1 30); do agent_up && { say "agent 就绪"; return 0; }; sleep 2; done
  # 健康检查失败可能是 ready=false，仍算"进程在"，用端口判断
  if pgrep -f "runtime.py serve --port ${AGENT_PORT}" >/dev/null; then
    say "⚠ agent 进程在，但 health 未通过（检查 ready/令牌）"
    return 0
  fi
  say "✗ agent 60 秒内未起来"
  return 1
}

# ---- 首次启动 ----
model_up || start_model
agent_up || start_agent

say "进入守护循环，间隔 ${CHECK_INTERVAL}s，日志 $LOG_DIR"
FAIL_MODEL=0
FAIL_AGENT=0
while true; do
  sleep "$CHECK_INTERVAL"

  if model_up; then
    FAIL_MODEL=0
  else
    FAIL_MODEL=$((FAIL_MODEL+1))
    say "⚠ 模型服务无响应（连续 $FAIL_MODEL 次）"
    # 连续两次才重启，避免瞬时抖动导致反复拉起
    if [ "$FAIL_MODEL" -ge 2 ]; then
      say "重启 llama-server"
      pkill -f "llama-server -m" 2>/dev/null; sleep 3
      start_model && FAIL_MODEL=0
    fi
  fi

  if pgrep -f "runtime.py serve --port ${AGENT_PORT}" >/dev/null; then
    FAIL_AGENT=0
  else
    FAIL_AGENT=$((FAIL_AGENT+1))
    say "⚠ agent 服务进程不在（连续 $FAIL_AGENT 次），重启"
    start_agent && FAIL_AGENT=0
  fi
done
