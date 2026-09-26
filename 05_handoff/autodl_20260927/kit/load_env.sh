#!/usr/bin/env bash
# Usage: source ./load_env.sh
_rtl_kit_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -f "$_rtl_kit_dir/env.local.sh" ]]; then
  echo 'Copy env.example.sh to env.local.sh and set actual paths first.'
  return 1
fi
source "$_rtl_kit_dir/env.local.sh"
if [[ ! -f "$XILINX_VIVADO/settings64.sh" ]]; then
  echo 'Vivado settings64.sh not found. Correct XILINX_VIVADO.'
  return 1
fi
source "$XILINX_VIVADO/settings64.sh"
mkdir -p "$EDA_TMP"
unset _rtl_kit_dir
