#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")" && pwd)"
server="${LLAMA_SERVER:-llama-server}"
model="${LLM_MODEL_PATH:-$root/model/qwen2.5-coder-7b-instruct-q4_k_m.gguf}"

if [ ! -f "$model" ]; then
  echo "model not found: $model" >&2
  exit 1
fi

exec "$server" \
  --model "$model" \
  --host "${LLM_HOST:-127.0.0.1}" \
  --port "${LLM_PORT:-8000}" \
  --ctx-size "${LLM_CONTEXT:-8192}" \
  --n-gpu-layers "${LLM_GPU_LAYERS:-0}"
