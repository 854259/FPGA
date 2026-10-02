#!/bin/bash
# 线程数调优（第三版）：客户端计时，最可靠。
set -u
BIN=/workspace/team/tools/llama-build/bin/llama-server
MODEL=/workspace/team/models/Qwen3.6-27B-Q4_K_M.gguf
LOG=/workspace/team/model-deployment/qwen-server.log
OUT=/workspace/team/runs/fpga_owner/thread_tune_20261003
mkdir -p "$OUT"; : > "$OUT/results3.txt"

health_ok() { curl -s -o /dev/null -m 2 http://127.0.0.1:8000/health 2>/dev/null; }
port_busy() { ss -ltn 2>/dev/null | grep -q ":8000 "; }

stop_server() {
  pkill -f "llama-server -m" 2>/dev/null
  for _ in $(seq 1 40); do
    if ! health_ok && ! port_busy; then return 0; fi
    sleep 1
  done
  pkill -9 -f "llama-server -m" 2>/dev/null; sleep 3
  ! health_ok && ! port_busy
}

bench() {
  local label="$1"
  local body='{"model":"Qwen3.6-27B-Q4_K_M","messages":[{"role":"user","content":"Count from 1 to 300, one number per line. No other text."}],"max_tokens":700,"temperature":0}'
  local tot=0 n=0
  for i in 1 2 3; do
    local t
    t=$(curl -s http://127.0.0.1:8000/v1/chat/completions -H 'Content-Type: application/json' \
        -d "$body" -o "$OUT/$label.$i.json" -m 300 -w '%{time_total}')
    local toks
    toks=$(python3 -c "import json;print(json.load(open('$OUT/$label.$i.json')).get('usage',{}).get('completion_tokens',0))" 2>/dev/null)
    [ -z "$toks" ] && toks=0
    local tps
    tps=$(python3 -c "print('%.1f' % ($toks/$t)) if $t>0 and $toks>0 else print('0')" 2>/dev/null)
    echo "      第 $i 次: ${toks} tokens / ${t}s = ${tps} tok/s"
    tot=$(python3 -c "print($tot+$tps)"); n=$((n+1))
    sleep 1
  done
  local avg
  avg=$(python3 -c "print('%.1f' % ($tot/$n))")
  echo ">>> -t $label 平均 ${avg} tok/s" | tee -a "$OUT/results3.txt"
}

BASE=(-m "$MODEL" --alias Qwen3.6-27B-Q4_K_M --host 127.0.0.1 --port 8000 -ngl 99 -c 16384 -np 1 --reasoning off)

restore() {
  echo; echo "[trap] 恢复正常服务"
  stop_server >/dev/null 2>&1
  nohup "$BIN" "${BASE[@]}" -t "${KEEP_T:-64}" >>"$LOG" 2>&1 &
  for _ in $(seq 1 90); do health_ok && break; sleep 2; done
  if health_ok; then
    echo "[trap] ✓ 服务在跑: $(ps -p $(pgrep -f 'llama-server -m'|head -1) -o args= | grep -oE '\-t [0-9]+')"
  else
    echo "[trap] ✗ 服务未起来"
  fi
}
trap restore EXIT

for T in 8 64 32 128; do
  echo
  echo "=== -t $T ==="
  stop_server || { echo "    端口未释放，跳过"; continue; }
  nohup "$BIN" "${BASE[@]}" -t "$T" >>"$LOG" 2>&1 &
  ok=0
  for _ in $(seq 1 90); do health_ok && { ok=1; break; }; sleep 2; done
  [ "$ok" = 1 ] || { echo "    ✗ 启动失败"; continue; }
  pid=$(pgrep -f "llama-server -m" | head -1)
  echo "    PID=$pid  $(ps -p $pid -o args= | grep -oE '\-t [0-9]+')"
  sleep 2
  bench "$T"
done
