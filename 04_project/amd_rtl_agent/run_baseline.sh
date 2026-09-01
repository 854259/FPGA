#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: $0 problem.txt output.sv" >&2
  exit 2
fi

root="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$root/agent.py" baseline --problem "$1" --output "$2"
