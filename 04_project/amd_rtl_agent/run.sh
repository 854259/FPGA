#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 2 ] || [ "$#" -gt 4 ]; then
  echo "usage: $0 problem.txt output_dir [test.sv] [ref.sv]" >&2
  exit 2
fi

root="$(cd "$(dirname "$0")" && pwd)"
args=(run --problem "$1" --output-dir "$2")
if [ "$#" -ge 3 ]; then args+=(--testbench "$3"); fi
if [ "$#" -ge 4 ]; then args+=(--reference "$4"); fi
exec python3 "$root/agent.py" "${args[@]}"
