#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
work_dir="$(mktemp -d)"
trap 'rm -rf -- "${work_dir}"' EXIT

docker run --rm --network none \
  --entrypoint llama-server \
  amd-rtl-agent:dev --version

docker run --rm --network none \
  --entrypoint bash \
  -v "${root}/tests:/tests:ro" \
  amd-rtl-agent:dev -lc '
    /workspace/serve.sh >/tmp/llama-server.log 2>&1 &
    server_pid=$!
    trap '\''kill "${server_pid}" 2>/dev/null || true'\'' EXIT
    python3 /tests/container_model_health.py
  '

docker run --rm --network none \
  -e LLM_MOCK_FILE=/input/mock_responses.json \
  -v "${root}/tests/fixtures:/input:ro" \
  -v "${work_dir}:/output" \
  amd-rtl-agent:dev \
  run --problem /input/problem.txt --output-dir /output --skip-eda

test -s "${work_dir}/result.json"
python3 - "${work_dir}/result.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    result = json.load(handle)
assert len(result["samples"]) == 5
assert result["pass_at_1"] is True
assert result["pass_at_5"] is True
print("CONTAINER_OFFLINE_SMOKE=PASS")
PY

docker image inspect amd-rtl-agent:dev --format 'image={{.Id}} bytes={{.Size}}'
