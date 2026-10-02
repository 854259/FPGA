#!/usr/bin/env bash
# Start the local inference service used by both run.sh (agent) and run_baseline.sh.
# Binds loopback only; the contest tunnel reaches 127.0.0.1, not 0.0.0.0.
set -euo pipefail

MODEL_PATH="${MODEL_PATH:-/opt/models/Qwen3.6-27B-Q4_K_M.gguf}"
LLAMA_BIN="${LLAMA_BIN:-/opt/llama/llama-server}"
MODEL_ALIAS="${MODEL_ALIAS:-Qwen3.6-27B-Q4_K_M}"
PORT="${MODEL_PORT:-8000}"
CTX="${MODEL_CTX:-16384}"
NGL="${MODEL_NGL:-99}"
THREADS="${MODEL_THREADS:-8}"

if [ ! -f "$MODEL_PATH" ]; then
  echo "model weights not found: $MODEL_PATH" >&2
  echo "place the Q4_K_M GGUF there, or set MODEL_PATH" >&2
  exit 1
fi
if [ ! -x "$LLAMA_BIN" ]; then
  echo "llama-server not found or not executable: $LLAMA_BIN" >&2
  exit 1
fi

# --reasoning off keeps Qwen-family templates from opening a <think> block, which
# otherwise consumes the output budget and truncates RTL. Verified by response smoke.
exec "$LLAMA_BIN" \
  -m "$MODEL_PATH" \
  --alias "$MODEL_ALIAS" \
  --host 127.0.0.1 \
  --port "$PORT" \
  -ngl "$NGL" \
  -c "$CTX" \
  -np 1 \
  -t "$THREADS" \
  --reasoning off
