#!/usr/bin/env bash
set -eo pipefail
exec python3 "$(dirname "$0")/agent/runtime.py" run "$1" "$2"
