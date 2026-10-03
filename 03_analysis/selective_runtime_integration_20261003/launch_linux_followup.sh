#!/usr/bin/env bash
# UNRUN. Invoke using nohup on the authorized AMD host, from an isolated fixed-SHA export.
set -euo pipefail
if [ "$#" -ne 6 ]; then
  echo 'usage: bash launch_linux_followup.sh SOURCE_ROOT NEW_RUN_ROOT KIT_ROOT MODEL_PID MODEL_NAME VIVADO_BIN' >&2
  exit 2
fi
SRC=$(realpath "$1")
RUN=$(realpath -m "$2")
KIT=$(realpath "$3")
MODEL_PID=$4
MODEL_NAME=$5
VIVADO_BIN=$(realpath "$6")
BASE="$SRC/03_analysis/selective_runtime_integration_20261003"
test ! -e "$RUN"
mkdir -p "$RUN"
cp "$SRC/DELIVERY_COMMIT" "$RUN/DELIVERY_COMMIT"
export PYTHONDONTWRITEBYTECODE=1
export VIVADO_BIN
export PATH="$VIVADO_BIN:$PATH"
# Preserve existing license/library bindings set by the authorized SSH task.
export NO_PROXY=127.0.0.1,localhost,::1
export no_proxy="$NO_PROXY"
OWNER="selective_$(basename "$RUN")_$$"
guard() {
  python3 -B "$BASE/resource_guard.py" --kit "$KIT" --model-pid "$MODEL_PID" \
    --model-name "$MODEL_NAME" --owner "$OWNER" --guard-out "$RUN/guard-$1" \
    --stage-timeout-s 2400 --slot-minutes 60 -- "${@:2}"
}
guard engineering python3 -B "$BASE/linux_preflight.py" engineering \
  --out "$RUN/engineering" --vivado-bin "$VIVADO_BIN" --seconds 90 \
  --resource-check '{resource_check}'
guard functional python3 -B "$BASE/linux_preflight.py" functional \
  --out "$RUN/functional" --vivado-bin "$VIVADO_BIN" --seconds 90 \
  --engineering-report "$RUN/engineering/summary.json" --resource-check '{resource_check}'
guard paired python3 -B "$BASE/paired_next/paired_checkpoint.py" run \
  --out "$RUN/paired" --kit "$KIT" --endpoint http://127.0.0.1:8000/v1 \
  --model "$MODEL_NAME" --engineering-report "$RUN/engineering/summary.json" \
  --forced-report "$RUN/functional/summary.json" --resource-check '{resource_check}'
echo 'Three isolated stages ended with successful evidence gates. Read summaries; this is not a deployment or score claim.'
