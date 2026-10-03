#!/usr/bin/env bash
# 一键起服务 + 守护，保证比赛期间"一直不退出，守着一个端口"（契约 ①）。
#
# 为什么需要这个
# --------------
# 2026-10-03 排查发现：实例上【没有任何守护机制】——0 个 systemd 单元、0 条 cron、
# 没有 watchdog。契约第 120 行写明：任何失败一律按 L0，不重试。也就是说，服务在
# 比赛途中挂掉之后的每一个样本都会是 0 分。
#
# 设计要点（第一版在评审中被指出三个问题，这里逐条修掉）
# ------------------------------------------------------
#  1) 就绪判断不能只看"curl 有没有返回"。
#     HTTP 401 / 500 / ready:false 都会让 curl 返回 0。现在解析状态码与 ready 字段。
#  2) 重启不能对共享实例用宽泛 pkill。
#     现在只动【自己启动、且已核验归属】的 PID；别人的进程一律不碰。
#  3) 要区分"进程死了"与"进程活着但没就绪"。
#     ready:false 是配置信号，不是崩溃——反复重启只会让它永远起不来。这种情况
#     只告警，不重启。
#
# 用法
# ----
#   FPGACHINA_TOKEN=xxx nohup bash serve_all.sh > /workspace/team/serve_all.log 2>&1 &
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
MODEL_PIDFILE="$LOG_DIR/llama-server.pid"
AGENT_PIDFILE="$LOG_DIR/agent-serve.pid"

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

# --- 就绪判断：返回 0 表示"活着且就绪"，1 表示"活着但未就绪"，2 表示"无响应" ---
# 用两个变量分别拿状态码和正文，避免 curl 的退出码把 401/500 也当成成功。
http_probe() {  # $1=url $2=extra curl args...
  local url="$1"; shift
  local body code
  body=$(curl -s -m 5 -w '\n%{http_code}' "$@" "$url" 2>/dev/null) || return 2
  code=$(printf '%s' "$body" | tail -n1)
  body=$(printf '%s' "$body" | sed '$d')
  [ -z "$code" ] && return 2
  [ "$code" = "000" ] && return 2
  printf '%s\n%s' "$code" "$body"
}

model_state() {
  local out code
  out=$(http_probe "http://127.0.0.1:${MODEL_PORT}/v1/models") || return 2
  code=$(printf '%s' "$out" | head -n1)
  [ "$code" = "200" ] || return 1
  printf '%s' "$out" | tail -n +2 | grep -q "$MODEL_NAME" || return 1
  return 0
}

agent_state() {
  local out code body
  out=$(http_probe "http://127.0.0.1:${AGENT_PORT}/v1/health" \
        -H "Authorization: Bearer ${FPGACHINA_TOKEN}") || return 2
  code=$(printf '%s' "$out" | head -n1)
  body=$(printf '%s' "$out" | tail -n +2)
  [ "$code" = "200" ] || return 1
  # 必须真的 ready:true；只有进程在、health 返回 false 不算就绪
  printf '%s' "$body" | grep -q '"ready"[[:space:]]*:[[:space:]]*true' || return 1
  return 0
}

# --- 进程归属核验：只有命令行同时含我们自己的标识才认，避免误杀别人的进程 ---
pid_is_ours() {  # $1=pid $2=匹配串
  local pid="$1" want="$2"
  [ -n "$pid" ] || return 1
  [ -r "/proc/$pid/cmdline" ] || return 1
  tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q -- "$want"
}

stop_ours() {  # $1=pidfile $2=匹配串
  local pidfile="$1" want="$2" pid
  pid=$(cat "$pidfile" 2>/dev/null || true)
  if [ -z "$pid" ]; then return 0; fi
  if pid_is_ours "$pid" "$want"; then
    say "停止自己启动的进程 PID=$pid"
    kill -TERM "$pid" 2>/dev/null
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
    kill -9 "$pid" 2>/dev/null
  else
    say "PID=$pid 已不属于本脚本（命令行不匹配），不动它"
  fi
  rm -f "$pidfile"
}

start_model() {
  say "启动 llama-server（$MODEL_PATH）"
  nohup "$LLAMA_BIN" -m "$MODEL_PATH" --alias "$MODEL_NAME" \
    --host 127.0.0.1 --port "$MODEL_PORT" \
    -ngl "${MODEL_NGL:-99}" -c "${MODEL_CTX:-16384}" -np 1 \
    -t "${MODEL_THREADS:-8}" --reasoning off \
    >> "$LOG_DIR/llama-server-$(date -u +%Y%m%d).log" 2>&1 &
  echo $! > "$MODEL_PIDFILE"
  # 权重在 page cache 里时约 5 秒就绪；给足 180 秒
  for _ in $(seq 1 90); do
    model_state && { say "模型就绪"; return 0; }
    sleep 2
  done
  say "✗ 模型 180 秒内未就绪"
  return 1
}

start_agent() {
  say "启动 agent HTTP 服务（端口 $AGENT_PORT）"
  ( cd "$KIT" && nohup python3 -B submission/agent/runtime.py serve --port "$AGENT_PORT" \
      >> "$LOG_DIR/agent-serve-$(date -u +%Y%m%d).log" 2>&1 & echo $! > "$AGENT_PIDFILE" )
  for _ in $(seq 1 30); do
    case $(agent_state; echo $?) in
      0) say "agent 就绪"; return 0 ;;
      1) say "⚠ agent 进程在但未就绪（ready=false 或非 200），继续等"; sleep 2 ;;
      *) sleep 2 ;;
    esac
  done
  say "✗ agent 60 秒内未就绪"
  return 1
}

# ---- 首次启动 ----
# 必须区分三种状态，不能写成 `state || start`：
#   0 = 已就绪；1 = 有响应但未就绪（配置问题，重复启动只会起第二个实例）；
#   2 = 无响应（这才是真的没起来）。
# 第一版用 `model_state || start_model` 把 1 也当成"没起来"，与循环阶段
# "只告警不重启"的策略自相矛盾，会重复拉起进程。
case $(model_state; echo $?) in
  0) say "模型已就绪" ;;
  1) say "⚠ 模型有响应但未就绪，不重复启动（查 $LOG_DIR 下的日志）" ;;
  *) start_model ;;
esac
case $(agent_state; echo $?) in
  0) say "agent 已就绪" ;;
  1) say "⚠ agent 在跑但未就绪（ready=false 或非 200），不重复启动；查令牌与 ready 条件" ;;
  *) start_agent ;;
esac
if [ ! -f "$AGENT_PIDFILE" ]; then
  say "⚠ 没有 $AGENT_PIDFILE，本脚本无法确认 agent 进程归属，循环中只会告警不会杀"
fi

say "进入守护循环，间隔 ${CHECK_INTERVAL}s，日志 $LOG_DIR"
FAIL_MODEL=0
FAIL_AGENT=0
NOTREADY_AGENT=0

while true; do
  sleep "$CHECK_INTERVAL"

  # 模型：无响应才重启；有响应但未就绪只告警（配置问题，重启无用）
  case $(model_state; echo $?) in
    0) FAIL_MODEL=0 ;;
    1) FAIL_MODEL=0; say "⚠ 模型服务有响应但未就绪" ;;
    *)
      FAIL_MODEL=$((FAIL_MODEL+1))
      say "⚠ 模型服务无响应（连续 $FAIL_MODEL 次）"
      if [ "$FAIL_MODEL" -ge 2 ]; then
        stop_ours "$MODEL_PIDFILE" "llama-server"
        start_model && FAIL_MODEL=0
      fi
      ;;
  esac

  # agent：三态处理。
  #   0/1 -> 活着，不重启（1 是配置问题）
  #   2   -> 无响应：只有确认"我们启动的那个进程确实不在了"才重启；
  #          如果端口被别人的进程占着，只告警，不动它。
  AGENT_PID=$(cat "$AGENT_PIDFILE" 2>/dev/null || true)
  case $(agent_state; echo $?) in
    0) FAIL_AGENT=0; NOTREADY_AGENT=0 ;;
    1)
      FAIL_AGENT=0
      NOTREADY_AGENT=$((NOTREADY_AGENT+1))
      say "⚠ agent 在跑但 health 未就绪（连续 $NOTREADY_AGENT 次）：查令牌 / ready 条件，不重启"
      ;;
    *)
      FAIL_AGENT=$((FAIL_AGENT+1))
      say "⚠ agent 无响应（连续 $FAIL_AGENT 次）"
      if [ "$FAIL_AGENT" -ge 2 ]; then
        if [ -z "$AGENT_PID" ] || ! kill -0 "$AGENT_PID" 2>/dev/null; then
          say "本脚本启动的进程已不在，重新启动"
          start_agent && FAIL_AGENT=0
        elif pid_is_ours "$AGENT_PID" "runtime.py serve"; then
          say "进程 $AGENT_PID 确认为本脚本启动且无响应，重启"
          stop_ours "$AGENT_PIDFILE" "runtime.py serve"
          start_agent && FAIL_AGENT=0
        else
          say "⚠ $AGENT_PORT 无响应，但占用者不是本脚本启动的，不动它"
        fi
      fi
      ;;
  esac
done
