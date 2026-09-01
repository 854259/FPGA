#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
revision="13fb94bfda8c8cf22497dc57b78f391a9acb426a"
filename="qwen2.5-coder-7b-instruct-q4_k_m.gguf"
expected_sha256="509287f78cb4d4cf6b3843734733b914b2c158e43e22a7f4bf5e963800894d3c"
expected_bytes="4683073536"
target="${MODEL_TARGET:-${root}/model/${filename}}"
partial="${target}.part"
url="https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/${revision}/${filename}?download=true"

mkdir -p "$(dirname "$target")"
if [ -f "$target" ]; then
  echo "${expected_sha256}  ${target}" | sha256sum --check --strict -
else
  curl --fail --location --retry 5 --retry-delay 3 --continue-at - \
    --output "$partial" "$url"
  actual_bytes="$(stat -c '%s' "$partial")"
  if [ "$actual_bytes" != "$expected_bytes" ]; then
    echo "unexpected model size: got ${actual_bytes}, expected ${expected_bytes}; partial file kept" >&2
    exit 1
  fi
  echo "${expected_sha256}  ${partial}" | sha256sum --check --strict -
  mv -- "$partial" "$target"
fi

printf 'MODEL_DOWNLOAD=PASS\nrevision=%s\npath=%s\nsha256=%s\nbytes=%s\n' \
  "$revision" "$target" "$expected_sha256" "$expected_bytes"
