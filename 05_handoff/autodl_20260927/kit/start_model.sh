#!/usr/bin/env bash
# Candidate NVFP4 launch only. Requires a preinstalled compatible vLLM environment.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
source ./env.local.sh
: "${MODEL_PATH:?Set MODEL_PATH first}"
if [[ ! -f "$MODEL_PATH/config.json" ]]; then
  echo 'Model weights/config not present. Download the locked revision first.' >&2
  exit 1
fi
command -v vllm >/dev/null
command -v nvidia-smi >/dev/null
python3 - <<'PY'
from importlib.metadata import version
import re
v = version('vllm')
print('vLLM:', v)
parts = re.match(r'(\d+)\.(\d+)', v)
if not parts or tuple(map(int, parts.groups())) < (0, 28):
    raise SystemExit('This candidate requires vLLM >= 0.28 per its SM120 recipe. Select a compatible environment.')
PY
mkdir -p logs
stamp="$(date +%Y%m%d_%H%M%S)_$$"
python3 -m pip freeze > "logs/inference_packages_$stamp.txt"
nvidia-smi > "logs/gpu_before_$stamp.txt"
# Both baseline and agent share this model and the same default chat template.
vllm serve "$MODEL_PATH" \
  --served-model-name "$MODEL_NAME" \
  --host 127.0.0.1 --port 8000 \
  --max-model-len 16384 --max-num-seqs 1 \
  --gpu-memory-utilization 0.85 \
  --kv-cache-dtype fp8 --attention-backend flashinfer \
  --reasoning-parser qwen3 \
  2>&1 | tee "logs/model_$stamp.log"
