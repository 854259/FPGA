#!/usr/bin/env bash
# =====================================================================
# deploy_accept_v2.sh -- task C of 05_handoff/AI_EXECUTION_PLAN_20261003.md
#
# Controlled-start deployment acceptance for the AMD RTL agent service.
#
# Differences from /workspace/team/deploy_accept.sh (c7261bf61c9b1a12):
#   1. Fault injection is allowed ONLY against processes this run started
#      AND re-verified immediately before the signal. The gate checks:
#        pid alive and not a zombie
#        + /proc/PID/stat field 22 (starttime) == value recorded at spawn
#        + cmdline contains every required token (binary, model path, alias,
#          port)
#        + /proc/PID/exe resolves to the expected executable
#        + the listening socket on the expected port belongs to this pid
#      A pgrep string match is NOT authority to kill anything.
#   2. A model that was already listening before this run is EXTERNAL:
#      never adopted, never killed, and the model-recovery item is
#      recorded UNTESTED (never PASS). Taking it over requires the
#      operator to arrange a separate owned-model test; this script never
#      kills a pre-existing shared model, including when a handover flag is set.
#   3. Every recovery must show: correct HTTP status + JSON fields +
#      ready:true + model identity from /v1/models equal to --alias +
#      a non-empty /v1/solve answer + an official-judge level == 3 on
#      one fixed small task at L3. HTTP 200 alone is never a recovery PASS.
#   4. Covers short deadline, malformed requests, oversized body,
#      concurrency, and post-concurrency recovery; SIGTERM must exit
#      within the contract limit (10 s, official_reference/docs/
#      API_CONTRACT.md L287) with no leftover descendants.
#   5. Cleanup only ever stops resources this run started and re-verified.
#      It never stops the only guardian and then claims "standing by".
#      Full-machine reboot autostart is UNTESTED and says so.
#   6. The start entry must come from the final submission package. The
#      deployed copy and submission/serve/serve_all.sh are hashed and
#      compared; a missing file or mismatch blocks --execute.
#
# Exit codes:
#   execute : 0 = every tested item PASS and nothing UNTESTED
#             1 = at least one FAIL, or a gate refused to run
#             2 = no FAIL but at least one UNTESTED (NOT an acceptance)
#   dry-run : never 0; 2 normally, 1 if the entry-hash gate fails
#   self-test: 0 = unit tests passed (this is NOT deployment acceptance)
#
# Usage:
#   bash deploy_accept_v2.sh --dry-run
#   bash deploy_accept_v2.sh --self-test
#   FPGACHINA_TOKEN=<real token> ACCEPT_SLOT_OWNER=<me> \
#     bash deploy_accept_v2.sh --execute [--restore|--keep-guardian]
#
# ASCII-only, LF newlines, UTF-8 without BOM by construction.
# =====================================================================
set -uo pipefail
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

# ---------------------------------------------------------------- config
KIT="${KIT:-/workspace/team/tasks/autodl-rtl-kit/project}"
ENTRY_DEPLOY="${ENTRY_DEPLOY:-/workspace/team/serve_all.sh}"
ENTRY_SUBMISSION="${ENTRY_SUBMISSION:-$KIT/submission/serve/serve_all.sh}"
JUDGE="${JUDGE:-$KIT/official_reference/selftest/judge.py}"
MANIFEST="${MANIFEST:-$KIT/submission/manifest.json}"
RUN_META="${RUN_META:-/workspace/team/runs/fpga_owner/full156_runtime728_20261003/full/experiment.json}"
FIXED_TASK="${FIXED_TASK:-$KIT/bench/tasks_veval/Prob007_wire}"
SLOT_FILE="${SLOT_FILE:-/workspace/team/SLOT.lock}"
VIVADO_BIN="${VIVADO_BIN:-/workspace/AMD/2026.1/Vivado/bin}"
XILINX_LIC="${XILINX_LIC:-/workspace/team/Xilinx.lic}"
LLAMA_BIN="${LLAMA_BIN:-/workspace/team/tools/llama-build/bin/llama-server}"
MODEL_PATH="${MODEL_PATH:-/workspace/team/models/Qwen3.6-27B-Q4_K_M.gguf}"
MODEL_NAME="${MODEL_NAME:-Qwen3.6-27B-Q4_K_M}"
AGENT_PORT="${AGENT_PORT:-7860}"
MODEL_PORT="${MODEL_PORT:-8000}"
CHECK_INTERVAL="${CHECK_INTERVAL:-10}"
TERM_LIMIT_S="${TERM_LIMIT_S:-10}"
RESTART_WAIT_S="${RESTART_WAIT_S:-150}"
JUDGE_TIMEOUT_S="${JUDGE_TIMEOUT_S:-600}"
SOLVE_DEADLINE_S="${SOLVE_DEADLINE_S:-300}"
MAX_TOTAL_S="${MAX_TOTAL_S:-2700}"
TEST_TOKEN="deploy-accept-v2-test-token-not-production"

MODE="dry-run"
END_MODE="restore"
WITH_JUDGE=1
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="${ACCEPT_LOG_DIR:-/workspace/team/deploy_accept_v2_$STAMP}"

usage() { sed -n '2,56p' "$0" | sed 's/^# \{0,1\}//'; }
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)        MODE="dry-run" ;;
    --self-test)      MODE="self-test" ;;
    --execute)        MODE="execute" ;;
    --restore)        END_MODE="restore" ;;
    --keep-guardian)  END_MODE="keep-guardian" ;;
    --no-judge)       WITH_JUDGE=0 ;;
    -h|--help)        usage; exit 0 ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; usage; exit 64 ;;
  esac
  shift
done

# ---------------------------------------------------------------- state
N_PASS=0; N_FAIL=0; N_UNTESTED=0; N_INFO=0
HARD_GATE_FAIL=0
START_EPOCH=$(date +%s)
SELF_SHA=""
LIVE_LIST=0
EXTERNAL_MODEL_PID=""
EXTERNAL_MODEL_ST=""
PRE_MODEL_PIDS=""; PRE_AGENT_PIDS=""; PRE_GUARDIAN=""; PRE_EVAL=""; PRE_SLOT=""
PRE_MODEL_HTTP=""; PRE_AGENT_HTTP=""
ENTRY_DEPLOY_SHA=""; ENTRY_SUBMISSION_SHA=""; JUDGE_SHA=""
JUDGE_LEVEL=""
FIXED_PROMPT=""
ST_TRACK=()
INFLIGHT_BG=""
INFLIGHT_TREE=""
EDA_BASE=""

mkdir -p "$LOG"
RESULTS="$LOG/steps.txt"
JSON_OUT="$LOG/summary.json"
LEDGER="$LOG/ledger"
WORK="$LOG/work"
SERVE_LOGS="$LOG/serve_logs"
mkdir -p "$LEDGER" "$WORK" "$SERVE_LOGS"

say()  { printf '[%s] %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }
hr()   { printf '%s\n' "----------------------------------------------------------------"; }
sec()  { printf '\n== %s\n' "$*" | tee -a "$RESULTS"; }

record() { # $1=name $2=PASS|FAIL|UNTESTED|INFO $3=detail
  local name="$1" status="$2" detail="$3" line
  case "$status" in
    PASS)     N_PASS=$((N_PASS+1)) ;;
    FAIL)     N_FAIL=$((N_FAIL+1)) ;;
    UNTESTED) N_UNTESTED=$((N_UNTESTED+1)) ;;
    INFO)     N_INFO=$((N_INFO+1)) ;;
  esac
  line=$(printf '%-8s %-42s %s' "$status" "$name" "$detail")
  printf '%s\n' "$line"
  printf '%s\n' "$line" >> "$RESULTS"
}
elapsed_total()   { echo $(( $(date +%s) - START_EPOCH )); }
budget_exceeded() { [ "$(elapsed_total)" -gt "$MAX_TOTAL_S" ]; }

# ---------------------------------------------------------------- helpers on disk
write_helpers() {
  cat > "$WORK/jq.py" <<'PY'
import json, sys
args = sys.argv[1:]
mode, key = "get", None
if args and args[0] == "--keys":
    mode = "keys"
elif args and args[0] == "--len":
    mode, key = "len", args[1]
elif args and args[0] == "--rawkey":
    mode, key = "raw", args[1]
elif args:
    key = args[0]
try:
    doc = json.load(sys.stdin)
except Exception:
    print(""); raise SystemExit(0)
if mode == "keys":
    print(",".join(sorted(doc.keys())) if isinstance(doc, dict) else "")
    raise SystemExit(0)
if mode == "raw":
    cur = doc
    for part in key.split("|"):
        cur = cur.get(part) if isinstance(cur, dict) else None
        if cur is None: break
    print("" if cur is None else (cur if isinstance(cur, str) else json.dumps(cur, ensure_ascii=False)))
    raise SystemExit(0)
cur = doc
for part in (key or "").split("."):
    if part == "":
        break
    if isinstance(cur, list):
        try: cur = cur[int(part)]
        except Exception: cur = None
    elif isinstance(cur, dict):
        cur = cur.get(part)
    else:
        cur = None
    if cur is None: break
if mode == "len":
    print(len(cur) if isinstance(cur, (str, list, dict)) else 0)
elif cur is None:
    print("")
elif isinstance(cur, bool):
    print("true" if cur else "false")
elif isinstance(cur, str):
    print(cur)
else:
    print(json.dumps(cur, ensure_ascii=False))
PY
  cat > "$WORK/prochelp.py" <<'PY'
import os, sys
def fields(pid):
    try:
        raw = open("/proc/%d/stat" % pid).read()
    except OSError:
        return None
    i = raw.rfind(")")
    if i < 0:
        return None
    return raw[i+2:].split()
def listen_inode(port):
    want = ":%04X" % port
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines = open(path).read().splitlines()[1:]
        except OSError:
            continue
        for ln in lines:
            f = ln.split()
            if len(f) < 10 or f[3] != "0A":
                continue
            if f[1].split(":")[-1].upper() == want[1:]:
                return f[9]
    return ""
def main():
    cmd = sys.argv[1]
    if cmd == "starttime":
        f = fields(int(sys.argv[2])); print("" if not f else f[19])
    elif cmd == "state":
        f = fields(int(sys.argv[2])); print("" if not f else f[0])
    elif cmd == "ppid":
        f = fields(int(sys.argv[2])); print("" if not f else f[1])
    elif cmd == "descendants":
        root = int(sys.argv[2]); kids = {}
        for e in os.listdir("/proc"):
            if not e.isdigit(): continue
            f = fields(int(e))
            if not f: continue
            try: kids.setdefault(int(f[1]), []).append(int(e))
            except ValueError: pass
        out, stack = [], [root]
        while stack:
            for c in kids.get(stack.pop(), []):
                out.append(c); stack.append(c)
        print(" ".join(str(p) for p in out))
    elif cmd == "port_owner":
        ino = listen_inode(int(sys.argv[2]))
        if not ino:
            print(""); raise SystemExit(0)
        target = "socket:[%s]" % ino
        owners = []
        for e in sorted(os.listdir("/proc")):
            if not e.isdigit(): continue
            fddir = "/proc/%s/fd" % e
            try: fds = os.listdir(fddir)
            except OSError: continue
            for fd in fds:
                try:
                    if os.readlink(os.path.join(fddir, fd)) == target:
                        owners.append(int(e)); break
                except OSError:
                    continue
        print(" ".join(str(p) for p in owners))
    elif cmd == "listen_inode":
        print(listen_inode(int(sys.argv[2])))
    elif cmd == "eda":
        import re
        # Format: pid:ppid:pgrp:starttime:cmdline
        # fields() returns the remainder of /proc/PID/stat after "pid (comm) ":
        # index 0 = state, 1 = ppid, 2 = pgrp, 19 = starttime (overall field 22).
        pat = re.compile(sys.argv[2])
        rows = []
        for e in os.listdir("/proc"):
            if not e.isdigit():
                continue
            try:
                cl = open("/proc/%s/cmdline" % e, "rb").read().replace(b"\x00", b" ").decode("utf-8", "replace").strip()
            except OSError:
                continue
            if not cl or "prochelp.py" in cl or not pat.search(cl):
                continue
            f = fields(int(e))
            if not f or len(f) < 20:
                continue
            rows.append((int(e), "%s:%s:%s:%s:%s" % (e, f[1], f[2], f[19], cl[:150])))
        for _, r in sorted(rows):
            print(r)
main()
PY
}
PJ() { python3 "$WORK/prochelp.py" "$@" 2>/dev/null; }

# ---------------------------------------------------------------- proc helpers
proc_starttime() { PJ starttime "$1"; }
proc_state()     { PJ state "$1"; }
proc_ppid()      { PJ ppid "$1"; }
proc_cmdline()   { tr '\0' ' ' < "/proc/$1/cmdline" 2>/dev/null; }
proc_exe()       { readlink -f "/proc/$1/exe" 2>/dev/null; }
proc_alive() {
  [ -n "${1:-}" ] && [ -d "/proc/$1" ] || return 1
  [ "$(proc_state "$1")" != "Z" ] || return 1
  return 0
}
listen_inode()    { PJ listen_inode "$1"; }
port_owner_pids() { PJ port_owner "$1"; }
descendants_of()  { PJ descendants "$1"; }

# --- EDA / child-process residue -------------------------------------------------
# The contract-relevant failure mode is a parent that dies while its children keep
# running (documented twice: a pkill that left orphan Vivado synthesizers alive, and
# SIGTERM on the worker leaving EDA grandchildren re-parented to PID 1). A parent
# being gone is therefore NOT evidence of success: every start/stop step is compared
# against a baseline snapshot of the whole process table, by (pid, starttime).
EDA_RE="${EDA_RE:-Vivado|vivado|xelab|xsim|judge\.py|parallel_synth_helper|xsimk}"
SERVICE_RE="${SERVICE_RE:-llama-server|runtime\.py}"
eda_snapshot() { PJ eda "$EDA_RE"; }
service_snapshot() { PJ eda "$SERVICE_RE"; }
eda_keys()     { printf '%s\n' "$1" | awk -F: 'NF>4 {print $1":"$4}'; }
eda_orphans()  { printf '%s\n' "$1" | awk -F: 'NF>4 && $2==1 {print $1}'; }
eda_new() { # $1=baseline $2=current -> "pid:starttime" entries not in the baseline
  local base k out=""
  base=$(eda_keys "$1" | sort)
  for k in $(eda_keys "$2"); do
    printf '%s\n' "$base" | grep -qx -- "$k" || out="$out $k"
  done
  printf '%s' "$out"
}
eda_count() { eda_keys "$1" | grep -c . ; }
residue_step() { # $1=label $2=baseline ; records PASS/FAIL about new EDA processes
  local label="$1" base="$2" now new
  sleep 2   # let short-lived tools exit before calling a step clean
  now=$(eda_snapshot)
  new=$(eda_new "$base" "$now")
  if [ -z "$new" ]; then
    record "RESIDUE-$label" PASS "no new EDA process vs baseline (baseline had $(eda_count "$base"))"
  else
    record "RESIDUE-$label" FAIL "EDA process(es) appeared and are still alive:$new -- check ppid/pgid and cmdline before calling this step a success (includes this script's own official-judge runs)"
    printf '%s\n' "$now" | grep -E "^($(printf '%s' "$new" | tr ' ' '|' | sed 's/:.*//g')):" | sed 's/^/    /' | tee -a "$RESULTS"
  fi
}

listens_on() { # $1=pid $2=port
  local pid="$1" port="$2" ino target fd tgt
  ino=$(listen_inode "$port")
  [ -n "$ino" ] || return 1
  target="socket:[$ino]"
  for fd in /proc/$pid/fd/*; do
    [ -e "$fd" ] || continue
    tgt=$(readlink "$fd" 2>/dev/null) || continue
    [ "$tgt" = "$target" ] && return 0
  done
  return 1
}
tree_snapshot() { # $1=root pid -> "pid:starttime ..." for all descendants
  local p st out=""
  for p in $(descendants_of "$1"); do
    st=$(proc_starttime "$p")
    [ -n "$st" ] && out="$out $p:$st"
  done
  printf '%s' "$out"
}
tree_survivors() { # $1="pid:st ..." -> surviving pids
  local e p st out=""
  for e in $1; do
    p="${e%%:*}"; st="${e##*:}"
    [ -n "$p" ] && [ -n "$st" ] || continue
    if [ -d "/proc/$p" ] && [ "$(proc_state "$p")" != "Z" ] && [ "$(proc_starttime "$p")" = "$st" ]; then
      out="$out $p"
    fi
  done
  printf '%s' "$out"
}

# ---------------------------------------------------------------- ownership gate
owns_check() { # KIND PID STARTTIME -> "OK" or a refusal reason
  local kind="$1" pid="$2" st="$3" cmd exe tok want_exe now
  [ -n "$pid" ] || { echo "NO_PID_RECORDED"; return 1; }
  [ -d "/proc/$pid" ] || { echo "NO_SUCH_PROC"; return 1; }
  [ "$(proc_state "$pid")" != "Z" ] || { echo "ZOMBIE"; return 1; }
  [ -n "$st" ] || { echo "NO_STARTTIME_RECORDED"; return 1; }
  now=$(proc_starttime "$pid")
  [ "$now" = "$st" ] || { echo "STARTTIME_MISMATCH(now=$now,ledger=$st)"; return 1; }
  cmd=$(proc_cmdline "$pid")
  [ -n "$cmd" ] || { echo "EMPTY_CMDLINE"; return 1; }
  exe=$(proc_exe "$pid")
  case "$kind" in
    model)
      for tok in "$LLAMA_BIN" "$MODEL_PATH" "--alias $MODEL_NAME" "--port $MODEL_PORT"; do
        case "$cmd" in *"$tok"*) ;; *) echo "CMDLINE_MISSING[$tok]"; return 1 ;; esac
      done
      want_exe=$(readlink -f "$LLAMA_BIN" 2>/dev/null)
      { [ -n "$want_exe" ] && [ "$exe" = "$want_exe" ]; } || { echo "EXE_MISMATCH($exe)"; return 1; }
      listens_on "$pid" "$MODEL_PORT" || { echo "PORT_NOT_OWNED($MODEL_PORT)"; return 1; }
      ;;
    agent)
      for tok in "runtime.py" "serve" "--port $AGENT_PORT"; do
        case "$cmd" in *"$tok"*) ;; *) echo "CMDLINE_MISSING[$tok]"; return 1 ;; esac
      done
      case "$exe" in *python*) ;; *) echo "EXE_NOT_PYTHON($exe)"; return 1 ;; esac
      listens_on "$pid" "$AGENT_PORT" || { echo "PORT_NOT_OWNED($AGENT_PORT)"; return 1; }
      ;;
    guardian)
      case "$cmd" in *"$ENTRY_DEPLOY"*|*serve_all.sh*) ;; *) echo "CMDLINE_MISSING[serve_all.sh]"; return 1 ;; esac
      case "$exe" in *bash*|*/sh|*/dash) ;; *) echo "EXE_NOT_SHELL($exe)"; return 1 ;; esac
      ;;
    *) echo "UNKNOWN_KIND($kind)"; return 1 ;;
  esac
  echo "OK"; return 0
}

ledger_put() { printf '%s\n' "$2" > "$LEDGER/$1.pid"; proc_starttime "$2" > "$LEDGER/$1.starttime"; }
ledger_pid() { cat "$LEDGER/$1.pid" 2>/dev/null || true; }
ledger_st()  { cat "$LEDGER/$1.starttime" 2>/dev/null || true; }

ledger_adopt() { # $1=kind $2=pid -- refuse to adopt anything that pre-existed this run
  local kind="$1" pid="$2" name file birth
  name=$(printf '%s' "$kind" | tr 'a-z' 'A-Z')
  [ -n "$pid" ] || return 1
  [ "$pid" != "$(ledger_pid "$kind")" ] || return 0
  case " $PRE_MODEL_PIDS $PRE_AGENT_PIDS $PRE_GUARDIAN " in
    *" $pid "*) record "ADOPT-$name" FAIL "refusing to adopt pid $pid: it already existed before this run"; return 1 ;;
  esac
  case "$kind" in
    agent) file="$SERVE_LOGS/agent-serve.pid" ;;
    model) file="$SERVE_LOGS/llama-server.pid" ;;
    *) return 1 ;;
  esac
  birth=$(cat "$file.starttime" 2>/dev/null) || return 1
  [ -n "$birth" ] && [ "$(proc_starttime "$pid")" = "$birth" ] || return 1
  [ "$(proc_ppid "$pid")" = "$(ledger_pid guardian)" ] || return 1
  ledger_put "$kind" "$pid"
  return 0
}

# ---------------------------------------------------------------- http helpers
HTTP_CODE=""; HTTP_BODY=""
http_req() { # $1=timeout, rest = curl args
  local t="$1" bf; shift
  bf=$(mktemp "$WORK/body.XXXXXX") || return 1
  HTTP_CODE=$(curl -s -m "$t" -o "$bf" -w '%{http_code}' "$@" 2>/dev/null)
  [ -n "$HTTP_CODE" ] || HTTP_CODE="000"
  HTTP_BODY=$(cat "$bf" 2>/dev/null || true)
  rm -f "$bf"
}
tok_hdr() { printf 'Authorization: Bearer %s' "$1"; }

model_identity() { # "id|name" from /v1/models
  local mid mname bf1 bf2
  http_req 5 "http://127.0.0.1:$MODEL_PORT/v1/models"
  [ "$HTTP_CODE" = "200" ] || { printf ''; return 1; }
  bf1=$(mktemp "$WORK/mid.XXXXXX"); bf2=$(mktemp "$WORK/mname.XXXXXX")
  printf '%s' "$HTTP_BODY" | python3 "$WORK/jq.py" data.0.id > "$bf1" 2>/dev/null
  printf '%s' "$HTTP_BODY" | python3 "$WORK/jq.py" models.0.name > "$bf2" 2>/dev/null
  mid=$(cat "$bf1" 2>/dev/null); mname=$(cat "$bf2" 2>/dev/null)
  rm -f "$bf1" "$bf2"
  printf '%s|%s' "$mid" "$mname"
}
health_probe() { http_req 10 -H "$(tok_hdr "$1")" "http://127.0.0.1:$AGENT_PORT/v1/health"; }

agent_ready() { # strict readiness incl. model identity
  local tok="$1" ready track model ident id
  health_probe "$tok"
  [ "$HTTP_CODE" = "200" ] || { echo "health HTTP $HTTP_CODE"; return 1; }
  ready=$(printf '%s' "$HTTP_BODY" | python3 "$WORK/jq.py" ready)
  track=$(printf '%s' "$HTTP_BODY" | python3 "$WORK/jq.py" track)
  model=$(printf '%s' "$HTTP_BODY" | python3 "$WORK/jq.py" model)
  [ "$ready" = "true" ] || { echo "ready=$ready (want true)"; return 1; }
  [ "$track" = "rtl" ]  || { echo "track='$track' (want rtl)"; return 1; }
  [ "$model" = "$MODEL_NAME" ] || { echo "health.model='$model' (want $MODEL_NAME)"; return 1; }
  ident=$(model_identity) || { echo "/v1/models unreachable"; return 1; }
  id=${ident%%|*}
  [ "$id" = "$MODEL_NAME" ] || { echo "/v1/models id='$id' (want alias $MODEL_NAME)"; return 1; }
  echo "OK ready=true track=rtl health.model=$model models.id=$id"
  return 0
}
wait_agent_ready() { # $1=token $2=inner timeout s
  local t0; t0=$(date +%s)
  while :; do
    agent_ready "$1" >/dev/null 2>&1 && return 0
    [ $(( $(date +%s) - t0 )) -ge "$2" ] && return 1
    sleep 2
  done
}

solve_to() { # $1=token $2=task_id $3=prompt $4=deadline $5=outfile [$6=curl timeout]
  local tok="$1" tid="$2" prompt="$3" dl="$4" out="$5" payload tmo
  payload=$(python3 -c '
import json,sys
print(json.dumps({"task_id":sys.argv[1],"nonce":"v2-"+sys.argv[1],"mode":"agent",
                  "prompt":sys.argv[2],"interface":"","deadline_s":float(sys.argv[3])}))' \
    "$tid" "$prompt" "$dl")
  tmo="${6:-$(( ${dl%.*} + 30 ))}"
  http_req "$tmo" -X POST "http://127.0.0.1:$AGENT_PORT/v1/solve" \
    -H "$(tok_hdr "$tok")" -H 'Content-Type: application/json' -d "$payload"
  printf '%s' "$HTTP_BODY" > "$out"
}
solve_nonempty() { # $1=token $2=label -> echoes length of the solution
  local tok="$1" label="$2" keys len
  solve_to "$tok" "$label" "$FIXED_PROMPT" "$SOLVE_DEADLINE_S" "$WORK/$label.json"
  [ "$HTTP_CODE" = "200" ] || { echo "HTTP $HTTP_CODE"; return 1; }
  keys=$(printf '%s' "$HTTP_BODY" | python3 "$WORK/jq.py" --keys)
  [ "$keys" = "elapsed_s,solution,task_id,trace" ] || { echo "keys=[$keys]"; return 1; }
  [ "$(printf '%s' "$HTTP_BODY" | python3 "$WORK/jq.py" task_id)" = "$label" ] || { echo "task_id not echoed"; return 1; }
  len=$(printf '%s' "$HTTP_BODY" | python3 "$WORK/jq.py" --len solution)
  printf '%s' "$HTTP_BODY" | python3 "$WORK/jq.py" solution > "$WORK/$label.solution.v"
  [ "${len:-0}" -gt 0 ] || { echo "solution empty"; return 1; }
  echo "$len"; return 0
}
run_judge() { # $1=solution.v -> echoes level, sets JUDGE_LEVEL
  local sol="$1" out terr lvl judge_rc
  out=$(mktemp -d "$WORK/judge.XXXXXX") || return 1
  JUDGE_LEVEL=""
  [ -f "$JUDGE" ] || { echo "judge missing"; return 1; }
  [ -f "$FIXED_TASK/task.json" ] || { echo "fixed task missing"; return 1; }
  mkdir -p "$out/scratch" || return 1
  # Preserve the pinned judge's own tool work; --quiet can leave its outer log empty.
  SELFTEST_TMP="$out/scratch" SELFTEST_KEEP_WORK=1 \
  PATH="$VIVADO_BIN:$PATH" XILINXD_LICENSE_FILE="$XILINX_LIC" XILINX_VIVADO="${VIVADO_BIN%/bin}" \
    python3 "$JUDGE" --task "$FIXED_TASK" --solution "$sol" --outdir "$out" \
      --timeout "$JUDGE_TIMEOUT_S" --json "$out/verdict.json" > "$out/judge.stdout" 2>&1
  judge_rc=$?
  [ "$judge_rc" -eq 0 ] || { echo "judge process failed: $judge_rc (logs: $out)"; return 1; }
  [ -s "$out/verdict.json" ] || { echo "no verdict json"; return 1; }
  terr=$(python3 "$WORK/jq.py" tool_error < "$out/verdict.json")
  lvl=$(python3 "$WORK/jq.py" level < "$out/verdict.json")
  JUDGE_LEVEL="$lvl"
  [ -z "$terr" ] || { echo "tool_error: $terr"; return 1; }
  [ -n "$lvl" ] || { echo "no level"; return 1; }
  echo "$lvl"; return 0
}

verify_recovery() { # $1=token $2=label -- code+json+ready+identity+solve+judge
  local tok="$1" label="$2" msg len ident id jl rc=0
  sleep 1
  msg=$(agent_ready "$tok") && record "REC-$label-health" PASS "$msg" \
    || { record "REC-$label-health" FAIL "$msg"; rc=1; }
  ident=$(model_identity); id=${ident%%|*}
  if [ "${id:-}" = "$MODEL_NAME" ]; then
    record "REC-$label-model-identity" PASS "/v1/models id=$id == alias"
  else
    record "REC-$label-model-identity" FAIL "identity='${ident:-unreachable}'"; rc=1
  fi
  if [ "$rc" -eq 0 ]; then
    len=$(solve_nonempty "$tok" "rec-$label") \
      && record "REC-$label-solve" PASS "non-empty RTL ($len chars)" \
      || { record "REC-$label-solve" FAIL "$len"; rc=1; }
  else
    record "REC-$label-solve" FAIL "skipped: service not ready"
  fi
  if [ "$rc" -eq 0 ] && [ "$WITH_JUDGE" -eq 1 ]; then
    if run_judge "$WORK/rec-$label.solution.v" > "$WORK/rec-$label.judge-result" && [ "$JUDGE_LEVEL" = "3" ]; then
      record "REC-$label-judge" PASS "official judge L3 on $(basename "$FIXED_TASK")"
    else
      jl=$(cat "$WORK/rec-$label.judge-result")
      record "REC-$label-judge" FAIL "official judge failed or below L3: $jl"; rc=1
    fi
  elif [ "$WITH_JUDGE" -eq 0 ]; then
    record "REC-$label-judge" UNTESTED "--no-judge"
  else
    record "REC-$label-judge" UNTESTED "skipped: service not ready"
  fi
  return "$rc"
}

# ---------------------------------------------------------------- preflight
read_fixed_prompt() {
  FIXED_PROMPT=""
  [ -f "$FIXED_TASK/prompt.txt" ] && FIXED_PROMPT=$(cat "$FIXED_TASK/prompt.txt")
}
snapshot_posture() {
  PRE_MODEL_HTTP=$(curl -s -o /dev/null -w '%{http_code}' -m 3 "http://127.0.0.1:$MODEL_PORT/v1/models" 2>/dev/null)
  PRE_AGENT_HTTP=$(curl -s -o /dev/null -w '%{http_code}' -m 3 "http://127.0.0.1:$AGENT_PORT/v1/health" 2>/dev/null)
  PRE_MODEL_PIDS=$(port_owner_pids "$MODEL_PORT")
  PRE_AGENT_PIDS=$(port_owner_pids "$AGENT_PORT")
  PRE_GUARDIAN=$(pgrep -f serve_all.sh 2>/dev/null | tr '\n' ' ' | sed 's/ $//')
  PRE_EVAL=$(pgrep -af official_eval.py 2>/dev/null | tr '\n' ';' | sed 's/;$//')
  PRE_SLOT=$(head -n1 "$SLOT_FILE" 2>/dev/null || true)
}
preflight_hash() {
  ENTRY_DEPLOY_SHA=$(sha256sum "$ENTRY_DEPLOY" 2>/dev/null | awk '{print $1}')
  ENTRY_SUBMISSION_SHA=$(sha256sum "$ENTRY_SUBMISSION" 2>/dev/null | awk '{print $1}')
  : "${ENTRY_DEPLOY_SHA:=MISSING}"; : "${ENTRY_SUBMISSION_SHA:=MISSING}"
  JUDGE_SHA=$(sha256sum "$JUDGE" 2>/dev/null | awk '{print $1}'); : "${JUDGE_SHA:=MISSING}"
  printf 'deployed   entry %s\n           sha256 %s\n' "$ENTRY_DEPLOY" "$ENTRY_DEPLOY_SHA"
  printf 'submission entry %s\n           sha256 %s\n' "$ENTRY_SUBMISSION" "$ENTRY_SUBMISSION_SHA"
  printf 'official judge   %s\n           sha256 %s\n' "$JUDGE" "$JUDGE_SHA"
  if [ "$ENTRY_DEPLOY_SHA" != "MISSING" ] && [ "$ENTRY_DEPLOY_SHA" = "$ENTRY_SUBMISSION_SHA" ]; then
    record "ENTRY-HASH-MATCH" PASS "deployed copy == submission package"
  else
    record "ENTRY-HASH-MATCH" FAIL "deployed=$ENTRY_DEPLOY_SHA submission=$ENTRY_SUBMISSION_SHA (differs; not the same version)"
    HARD_GATE_FAIL=1
  fi
}
preflight_manifest() {
  if [ ! -f "$MANIFEST" ]; then
    record "MANIFEST-RUNTIME" FAIL "no manifest at $MANIFEST"; HARD_GATE_FAIL=1; return 1
  fi
  local declared path actual svc
  declared=$(python3 "$WORK/jq.py" runtime.sha256 < "$MANIFEST")
  path=$(python3 "$WORK/jq.py" runtime.path < "$MANIFEST")
  actual=""
  if [ -n "$path" ] && [ -f "$KIT/submission/$path" ]; then
    actual=$(sha256sum "$KIT/submission/$path" | awk '{print $1}')
  fi
  if [ -n "$declared" ] && [ "$declared" = "$actual" ]; then
    record "MANIFEST-RUNTIME" PASS "manifest runtime.sha256 == disk ($path)"
  else
    record "MANIFEST-RUNTIME" FAIL "manifest declares ${declared:-none} but disk $path = ${actual:-missing}: deployment metadata is stale"
    HARD_GATE_FAIL=1
  fi
  svc=$(python3 "$WORK/jq.py" serving.supervisor_sha256 < "$MANIFEST")
  path=$(python3 "$WORK/jq.py" serving.supervisor < "$MANIFEST")
  if [ "$path" != "serve/serve_all.sh" ] || [ "$svc" != "$ENTRY_SUBMISSION_SHA" ]; then
    record "MANIFEST-ENTRY" FAIL "supervisor path/hash does not match the submission entry"
    HARD_GATE_FAIL=1
  else
    record "MANIFEST-ENTRY" PASS "supervisor path and hash match the submission entry"
  fi
}
preflight_run_pin() { # entry version the running experiment recorded at its start
  if [ ! -f "$RUN_META" ]; then
    record "ENTRY-RUN-PINNED" UNTESTED "no experiment meta at $RUN_META"; return 0
  fi
  local pinned
  pinned=$(python3 "$WORK/jq.py" --rawkey "submission_sha256|serve/serve_all.sh" < "$RUN_META")
  if [ -z "$pinned" ]; then
    record "ENTRY-RUN-PINNED" UNTESTED "experiment meta records no hash for serve/serve_all.sh"
  elif [ "$pinned" = "$ENTRY_DEPLOY_SHA" ]; then
    record "ENTRY-RUN-PINNED" PASS "the running experiment recorded the same entry version as disk now"
  else
    record "ENTRY-RUN-PINNED" INFO "running experiment pinned serve/serve_all.sh=$pinned, disk=$ENTRY_DEPLOY_SHA: that run's provenance refers to the earlier version (serve_all.sh is not read by official_eval.py)"
  fi
}
preflight_old_script_probe() {
  local pick state
  pick=$(pgrep -f "llama-server -m" 2>/dev/null | head -1)
  [ -n "$pick" ] || { printf 'no llama-server process matched\n'; return 0; }
  state=$(proc_state "$pick")
  printf 'old script line 97: MPID=$(pgrep -f "llama-server -m" | head -1) -> %s\n' "$pick"
  printf '  state=%s exe=%s\n' "$state" "$(proc_exe "$pick")"
  printf '  cmdline=%s\n' "$(proc_cmdline "$pick")"
  case " $PRE_MODEL_PIDS " in
    *" $pick "*) printf '  -> this is the pre-existing model serving port %s; the old script would kill -9 it\n' "$MODEL_PORT" ;;
  esac
  printf 'full match list: %s\n' "$(pgrep -af 'llama-server' 2>/dev/null | tr '\n' '|')"
}

gate_execute() { # $1=probe to only report
  local why="" probe="${1:-}"
  [ -n "${FPGACHINA_TOKEN:-}" ] || why="${why}FPGACHINA_TOKEN unset; "
  if [ -n "${FPGACHINA_TOKEN:-}" ] && [ "$FPGACHINA_TOKEN" = "$TEST_TOKEN" ]; then
    why="${why}FPGACHINA_TOKEN is the built-in test token (the real grader would get 401); "
  fi
  [ -n "$PRE_EVAL" ] && why="${why}official_eval.py is running: $PRE_EVAL; "
  if [ -z "$PRE_SLOT" ] || [ -z "${ACCEPT_SLOT_OWNER:-}" ] || [ "$ACCEPT_SLOT_OWNER" != "$PRE_SLOT" ]; then
    why="${why}acquire the model slot first and set ACCEPT_SLOT_OWNER to its actual owner; "
  fi
  if [ "$HARD_GATE_FAIL" != "0" ]; then
    why="${why}package or entry validation failed; "
  fi
  if { [ "$PRE_AGENT_HTTP" != "000" ] || [ -n "$PRE_AGENT_PIDS" ]; } && [ -z "$(ledger_pid agent)" ]; then
    why="${why}port $AGENT_PORT already answers and is not ours; "
  fi
  [ -n "$PRE_GUARDIAN" ] && why="${why}another guardian exists; coordinate before starting a second supervisor; "
  [ "${ACCEPT_MODEL_HANDOVER:-0}" = "1" ] && why="${why}shared-model handover is disabled; test only a model started by this run; "
  if [ "$END_MODE" = "keep-guardian" ] && [ "${ACCEPT_PRODUCTION_TOKEN:-0}" != "1" ]; then
    why="${why}--keep-guardian requires ACCEPT_PRODUCTION_TOKEN=1; "
  fi
  if [ -n "$why" ]; then
    [ "$probe" = "probe" ] && record "EXECUTE-GATE" INFO "would refuse: $why" \
                            || record "EXECUTE-GATE" FAIL "refused: $why"
    return 1
  fi
  record "EXECUTE-GATE" PASS "token set, no eval running, slot held by operator, package verified"
  return 0
}

# ---------------------------------------------------------------- self-test
write_fake_listener() {
  cat > "$WORK/fake_listen.py" <<'PY'
import socket, sys, time
port = int(sys.argv[sys.argv.index("--port") + 1])
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", port))
s.listen(5)
time.sleep(3600)
PY
}
st_track() { ST_TRACK+=("$1:$(proc_starttime "$1"):$2:$3"); }   # pid:st:kind:port
st_sweep() {
  local e pid rest st kind port r
  for e in ${ST_TRACK[@]+"${ST_TRACK[@]}"}; do
    [ -n "$e" ] || continue
    pid="${e%%:*}"; rest="${e#*:}"; st="${rest%%:*}"; rest="${rest#*:}"
    kind="${rest%%:*}"; port="${rest##*:}"
    proc_alive "$pid" || continue
    case "$kind" in
      agent) AGENT_PORT="$port" ;;
      model) MODEL_PORT="$port"; LLAMA_BIN="$WORK/fakebin/llama-server"; MODEL_PATH="$WORK/fake-model.gguf" ;;
    esac
    r=$(owns_check "$kind" "$pid" "$st")
    if [ "$r" = "OK" ]; then
      kill -TERM "$pid" 2>/dev/null; sleep 0.3
      proc_alive "$pid" && kill -9 "$pid" 2>/dev/null
    else
      printf 'self-test sweep: pid %s not verifiable (%s), left alone\n' "$pid" "$r"
    fi
  done
  ST_TRACK=()
}

self_test() {
  local T=0 F=0 r p1 p2 st1 st2 d
  hr; printf 'SELF-TEST of the ownership gate (unit level)\n'
  printf 'Gate logic only. A pass here is NOT deployment acceptance.\n'; hr
  write_helpers; write_fake_listener
  local SA_AP="$AGENT_PORT" SA_MP="$MODEL_PORT" SA_LB="$LLAMA_BIN" SA_MPATH="$MODEL_PATH"
  local fa=18002 fb=18003 fm=18001
  for p in 18001 18002 18003; do
    if [ -n "$(listen_inode "$p")" ]; then printf 'port %s busy; aborting self-test\n' "$p"; return 1; fi
  done

  sec "case 1: live foreign process is refused (no ledger entry)"
  local ext; ext=$(port_owner_pids "$MODEL_PORT")
  if [ -n "$ext" ]; then
    r=$(owns_check model "$ext" "0")
    if [ "$r" = "OK" ]; then printf 'FAIL  live pid %s accepted\n' "$ext"; F=$((F+1))
    else printf 'PASS  live pid %s refused: %s\n' "$ext" "$r"; T=$((T+1)); fi
  else
    printf 'SKIP  nothing owns port %s\n' "$MODEL_PORT"
  fi

  sec "case 2..5: synthetic agent on port $fa"
  mkdir -p "$WORK/fakebin"
  cp -f "$WORK/fake_listen.py" "$WORK/runtime.py"
  nohup python3 "$WORK/runtime.py" serve --port "$fa" >/dev/null 2>&1 &
  p1=$!; sleep 1; st1=$(proc_starttime "$p1"); st_track "$p1" agent "$fa"
  AGENT_PORT="$fa"
  r=$(owns_check agent "$p1" "$st1")
  if [ "$r" = "OK" ]; then printf 'PASS  case2 synthetic listener accepted (pid=%s starttime=%s)\n' "$p1" "$st1"; T=$((T+1))
  else printf 'FAIL  case2 synthetic listener refused: %s\n' "$r"; F=$((F+1)); fi

  r=$(owns_check agent "$p1" "$((st1+1000))")
  if [ "$r" != "OK" ]; then printf 'PASS  case3 wrong starttime refused: %s\n' "$r"; T=$((T+1))
  else printf 'FAIL  case3 wrong starttime accepted\n'; F=$((F+1)); fi

  AGENT_PORT=18999
  r=$(owns_check agent "$p1" "$st1")
  if [ "$r" != "OK" ]; then printf 'PASS  case4 wrong port refused: %s\n' "$r"; T=$((T+1))
  else printf 'FAIL  case4 wrong port accepted\n'; F=$((F+1)); fi
  AGENT_PORT="$fa"

  kill -TERM "$p1" 2>/dev/null; sleep 1
  r=$(owns_check agent "$p1" "$st1")
  if [ "$r" != "OK" ]; then printf 'PASS  case5 dead pid refused: %s\n' "$r"; T=$((T+1))
  else printf 'FAIL  case5 dead pid accepted\n'; F=$((F+1)); fi

  sec "case 6: process that listens but is not the agent -> refused"
  nohup python3 -c 'import time; time.sleep(300)' >/dev/null 2>&1 &
  p2=$!; sleep 1; st2=$(proc_starttime "$p2")
  r=$(owns_check agent "$p2" "$st2")
  if [ "$r" != "OK" ]; then printf 'PASS  case6 non-agent listener refused: %s\n' "$r"; T=$((T+1))
  else printf 'FAIL  case6 non-agent listener accepted\n'; F=$((F+1)); fi
  kill -TERM "$p2" 2>/dev/null

  sec "case 7..9: synthetic model on port $fm"
  # The fake llama binary is a copy of python3, so the listener script must come
  # first as the script argument: python3 would read a leading -m as "run module".
  cp -f "$(command -v python3)" "$WORK/fakebin/llama-server"
  nohup "$WORK/fakebin/llama-server" "$WORK/fake_listen.py" -m "$WORK/fake-model.gguf" \
    --alias "$MODEL_NAME" --host 127.0.0.1 --port "$fm" -ngl 0 >/dev/null 2>&1 &
  p2=$!; sleep 1; st2=$(proc_starttime "$p2")
  MODEL_PORT="$fm"; LLAMA_BIN="$WORK/fakebin/llama-server"; MODEL_PATH="$WORK/fake-model.gguf"
  st_track "$p2" model "$fm"
  r=$(owns_check model "$p2" "$st2")
  if [ "$r" = "OK" ]; then printf 'PASS  case7 synthetic llama-shaped listener accepted (pid=%s)\n' "$p2"; T=$((T+1))
  else printf 'FAIL  case7 synthetic llama-shaped listener refused: %s\n' "$r"; F=$((F+1)); fi

  r=$(owns_check model "$p2" "$((st2+1000))")
  if [ "$r" != "OK" ]; then printf 'PASS  case8 wrong starttime refused: %s\n' "$r"; T=$((T+1))
  else printf 'FAIL  case8 wrong starttime accepted\n'; F=$((F+1)); fi

  kill -TERM "$p2" 2>/dev/null; sleep 1
  nohup "$WORK/fakebin/llama-server" "$WORK/fake_listen.py" -m "$WORK/other.gguf" \
    --alias WRONG_ALIAS --host 127.0.0.1 --port "$fm" -ngl 0 >/dev/null 2>&1 &
  p2=$!; sleep 1; st2=$(proc_starttime "$p2")
  r=$(owns_check model "$p2" "$st2")
  if [ "$r" != "OK" ]; then printf 'PASS  case9 wrong model path/alias refused: %s\n' "$r"; T=$((T+1))
  else printf 'FAIL  case9 wrong model path/alias accepted\n'; F=$((F+1)); fi
  kill -TERM "$p2" 2>/dev/null; sleep 1
  proc_alive "$p2" && { kill -9 "$p2" 2>/dev/null; printf 'note  case9 helper needed SIGKILL\n'; }

  sec "case 10: descendants enumeration"
  d=$(descendants_of $$)
  printf 'INFO  descendants_of(self): %s\n' "${d:-none}"

  sec "case 11: ledger refuses a pid that pre-existed the run"
  PRE_MODEL_PIDS="$ext"
  local sp=$N_PASS sf=$N_FAIL su=$N_UNTESTED si=$N_INFO
  if ledger_adopt model "$ext"; then
    printf 'FAIL  case11 pre-existing pid %s was adopted\n' "$ext"; F=$((F+1))
  else
    printf 'PASS  case11 pre-existing pid %s not adopted (refusal recorded)\n' "${ext:-none}"; T=$((T+1))
  fi
  N_PASS=$sp; N_FAIL=$sf; N_UNTESTED=$su; N_INFO=$si
  PRE_MODEL_PIDS=""

  AGENT_PORT="$SA_AP"; MODEL_PORT="$SA_MP"; LLAMA_BIN="$SA_LB"; MODEL_PATH="$SA_MPATH"
  st_sweep
  hr; printf 'SELF-TEST RESULT: pass=%s fail=%s\n' "$T" "$F"
  printf 'UNIT TESTS ARE NOT DEPLOYMENT ACCEPTANCE\n'; hr
  [ "$F" -eq 0 ] || return 1
  return 0
}

# ---------------------------------------------------------------- dry run
dry_run() {
  hr; printf 'DEPLOY ACCEPTANCE v2 -- DRY RUN (read-only, starts nothing)\n'
  printf 'self sha256: %s\n' "$SELF_SHA"; hr
  write_helpers; read_fixed_prompt
  sec "preflight: posture"
  snapshot_posture
  printf 'model port %s : HTTP %s  owner pid(s)=%s\n' "$MODEL_PORT" "$PRE_MODEL_HTTP" "${PRE_MODEL_PIDS:-none}"
  printf 'agent port %s : HTTP %s  owner pid(s)=%s\n' "$AGENT_PORT" "$PRE_AGENT_HTTP" "${PRE_AGENT_PIDS:-none}"
  printf 'guardian(serve_all.sh): %s\n' "${PRE_GUARDIAN:-none}"
  printf 'official_eval.py      : %s\n' "${PRE_EVAL:-none}"
  printf 'SLOT.lock owner       : %s\n' "${PRE_SLOT:-none}"
  printf '/v1/models identity   : %s\n' "$(model_identity)"
  record "DRY-POSTURE" INFO "model $MODEL_PORT/$PRE_MODEL_HTTP owner=${PRE_MODEL_PIDS:-none}; agent $AGENT_PORT/$PRE_AGENT_HTTP owner=${PRE_AGENT_PIDS:-none}; eval=${PRE_EVAL:-none}"

  sec "preflight: identity of the pre-existing model"
  local mp; mp=$(printf '%s' "$PRE_MODEL_PIDS" | awk '{print $1}')
  if [ -n "$mp" ]; then
    printf 'pid=%s state=%s starttime=%s\n' "$mp" "$(proc_state "$mp")" "$(proc_starttime "$mp")"
    printf 'exe=%s\n' "$(proc_exe "$mp")"
    printf 'cmdline=%s\n' "$(proc_cmdline "$mp")"
    printf 'owns LISTEN socket on %s: %s\n' "$MODEL_PORT" "$(listens_on "$mp" "$MODEL_PORT" && echo yes || echo no)"
    printf 'ownership gate with no ledger entry -> %s\n' "$(owns_check model "$mp" "0")"
    record "DRY-EXTERNAL-MODEL" INFO "pid $mp is external to this run: not adopted, not killed; model recovery UNTESTED"
  else
    record "DRY-EXTERNAL-MODEL" INFO "no process owns port $MODEL_PORT right now"
  fi

  sec "preflight: what the old script would have killed"
  preflight_old_script_probe

  sec "preflight: entry point provenance"
  preflight_hash

  sec "preflight: deployment metadata and run provenance"
  preflight_manifest
  preflight_run_pin

  sec "preflight: baseline of EDA child processes (report only, never cleaned)"
  EDA_BASE=$(eda_snapshot)
  printf '%s\n' "$EDA_BASE" | sed 's/^/    /'
  printf 'baseline EDA count=%s\n' "$(eda_count "$EDA_BASE")"
  printf 'orphans among them (ppid==1, re-parented): %s\n' "$(eda_orphans "$EDA_BASE" | tr '\n' ' ')"
  if command -v ps >/dev/null 2>&1; then
    printf 'ps cross-check (pid,ppid,pgid,etime,stat):\n'
    ps -eo pid,ppid,pgid,etime,stat,cmd 2>/dev/null | grep -E "vivado|xelab|xsim|judge.py" \
      | grep -v grep | sed 's/^/    /' | head -20
  fi
  printf 'service processes now:\n'
  service_snapshot | sed 's/^/    /'
  record "RESIDUE-BASELINE" INFO "$(eda_count "$EDA_BASE") EDA process(es) already running before this run (pre-existing, reported but never cleaned); orphans: $(eda_orphans "$EDA_BASE" | tr '\n' ' ')"

  sec "preflight: execute gates (evaluated, not executed)"
  local saved="$MODE"; MODE="execute"; gate_execute probe; MODE="$saved"

  sec "items a dry run leaves untested"
  local item
  for item in \
    "EXEC-START-guardian:start serve_all.sh from the submission entry" \
    "EXEC-READY:health ready:true with model identity" \
    "HTTP-CONTRACT:401/400/404/oversize cases" \
    "HTTP-SHORT-DEADLINE:deadline_s=1 -> 200 + empty solution" \
    "SOLVE-NONEMPTY:normal /v1/solve returns non-empty RTL" \
    "OFFICIAL-JUDGE:official judge level >= L1 on the fixed task" \
    "CONCURRENCY:two parallel solves then recovery" \
    "FAULT-A:verified agent SIGKILL -> guardian restart -> recovery" \
    "FAULT-B:verified model SIGKILL -> guardian restart -> recovery" \
    "SIGTERM:exits within ${TERM_LIMIT_S}s, no leftover descendants" \
    "END-STATE:post-run posture and guardian retention" \
    "REBOOT-AUTOSTART:full-machine reboot autostart" ; do
    record "${item%%:*}" UNTESTED "${item#*:}"
  done

  sec "verdict"
  printf 'PASS=%s FAIL=%s UNTESTED=%s INFO=%s\n' "$N_PASS" "$N_FAIL" "$N_UNTESTED" "$N_INFO"
  printf 'DRY RUN IS NOT AN ACCEPTANCE: nothing was started, killed or restarted.\n'
  printf 'A FAIL above marks a gate/state finding at this moment, not a test failure.\n'
  write_summary
  [ "$HARD_GATE_FAIL" -eq 0 ] || return 1
  return 2
}

# ---------------------------------------------------------------- execute
start_guardian() {
  nohup env FPGACHINA_TOKEN="$FPGACHINA_TOKEN" AGENT_PORT="$AGENT_PORT" MODEL_PORT="$MODEL_PORT" \
    KIT="$KIT" CHECK_INTERVAL="$CHECK_INTERVAL" LOG_DIR="$SERVE_LOGS" MODEL_PATH="$MODEL_PATH" \
    LLAMA_BIN="$LLAMA_BIN" MODEL_NAME="$MODEL_NAME" \
    bash "$ENTRY_DEPLOY" > "$LOG/serve_all.out" 2>&1 &
  local pid=$!
  sleep 1
  ledger_put guardian "$pid"
  printf 'guardian pid=%s starttime=%s entry=%s\n' "$pid" "$(proc_starttime "$pid")" "$ENTRY_DEPLOY"
}
refresh_started_pids() {
  local ap mp
  ap=$(cat "$SERVE_LOGS/agent-serve.pid" 2>/dev/null || true)
  mp=$(cat "$SERVE_LOGS/llama-server.pid" 2>/dev/null || true)
  [ -n "$ap" ] && ledger_adopt agent "$ap"
  [ -n "$mp" ] && ledger_adopt model "$mp"
}
fault_a_inflight_snapshot() { # $1=token $2=agent pid ; sets INFLIGHT_BG and INFLIGHT_TREE
    # Starts a real request so the agent has children to lose, snapshots them by
  # (pid, starttime) so orphans are still identifiable after re-parenting, and
  # waits for the caller to break the connection. The curl timeout is bounded so
  # the probe cannot hang for the full solve budget.
  ( solve_to "$1" "inflight" "$FIXED_PROMPT" "$SOLVE_DEADLINE_S" "$WORK/inflight.json" 45; \
    printf '%s' "$HTTP_CODE" > "$WORK/inflight.code" ) &
  INFLIGHT_BG=$!
  INFLIGHT_TREE=""
  for _ in $(seq 1 50); do
    kill -0 "$INFLIGHT_BG" 2>/dev/null || break
    INFLIGHT_TREE=$(tree_snapshot "$2")
    [ -n "$INFLIGHT_TREE" ] && break
    sleep 0.1
  done
  printf 'in-flight request started (bg pid %s); descendants so far: %s\n' \
    "$INFLIGHT_BG" "${INFLIGHT_TREE:-none}"
  [ -n "$INFLIGHT_TREE" ] && kill -0 "$INFLIGHT_BG" 2>/dev/null
}
inflight_reap() { # bounded wait for the in-flight probe after the fault
  local i
  [ -n "${INFLIGHT_BG:-}" ] || return 0
  for i in $(seq 1 60); do
    kill -0 "$INFLIGHT_BG" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "$INFLIGHT_BG" 2>/dev/null; then
    printf 'in-flight probe pid %s still running; killing it (it is ours)\n' "$INFLIGHT_BG"
    kill -TERM "$INFLIGHT_BG" 2>/dev/null
    sleep 1
    kill -9 "$INFLIGHT_BG" 2>/dev/null
  fi
  wait "$INFLIGHT_BG" 2>/dev/null
  INFLIGHT_BG=""
}

execute() {
  local r
  hr; printf 'DEPLOY ACCEPTANCE v2 -- EXECUTE (controlled)\n'
  printf 'self sha256: %s\n' "$SELF_SHA"; hr
  write_helpers; read_fixed_prompt
  [ -n "$FIXED_PROMPT" ] || { record "PRE-FIXED-TASK" FAIL "no prompt.txt under $FIXED_TASK"; return 1; }

  sec "preflight"
  snapshot_posture
  printf 'model %s HTTP %s owner %s\n' "$MODEL_PORT" "$PRE_MODEL_HTTP" "${PRE_MODEL_PIDS:-none}"
  printf 'agent %s HTTP %s owner %s\n' "$AGENT_PORT" "$PRE_AGENT_HTTP" "${PRE_AGENT_PIDS:-none}"
  printf 'eval  %s\nslot  %s\n' "${PRE_EVAL:-none}" "${PRE_SLOT:-none}"
  preflight_hash
  preflight_manifest
  preflight_run_pin
  EDA_BASE=$(eda_snapshot)
  record "RESIDUE-BASELINE" INFO "$(eda_count "$EDA_BASE") EDA process(es) pre-existed this run; they are never cleaned by this script"
  if ! gate_execute; then
    printf 'REFUSED: gates did not pass. Nothing was started.\n'
    write_summary; return 1
  fi
  if [ -n "$PRE_MODEL_PIDS" ]; then
    EXTERNAL_MODEL_PID=$(printf '%s' "$PRE_MODEL_PIDS" | awk '{print $1}')
    EXTERNAL_MODEL_ST=$(proc_starttime "$EXTERNAL_MODEL_PID")
    record "MODEL-PREEXISTING" UNTESTED "pid $EXTERNAL_MODEL_PID served $MODEL_PORT before this run: external, not adopted, not killed"
  fi

  sec "start from the submission entry"
  start_guardian
  record "EXEC-START-guardian" PASS "pid=$(ledger_pid guardian) starttime=$(ledger_st guardian) logs=$SERVE_LOGS"

  local i ready_ok=0
  for i in $(seq 1 $((RESTART_WAIT_S/2))); do
    refresh_started_pids
    wait_agent_ready "$FPGACHINA_TOKEN" 2 && { ready_ok=1; break; }
    budget_exceeded && break
  done
  if [ "$ready_ok" -eq 1 ]; then
    record "EXEC-READY" PASS "$(agent_ready "$FPGACHINA_TOKEN")"
  else
    record "EXEC-READY" FAIL "agent not ready within ${RESTART_WAIT_S}s"
    tail -n 20 "$LOG/serve_all.out" >> "$RESULTS" 2>/dev/null
    write_summary; return 1
  fi
  refresh_started_pids
  residue_step AFTER-START "$EDA_BASE"

  sec "http contract"
  local sh_code
  http_req 10 "http://127.0.0.1:$AGENT_PORT/v1/health"
  [ "$HTTP_CODE" = "401" ] && record "HTTP-NOTOKEN-health" PASS "401 as required" \
    || record "HTTP-NOTOKEN-health" FAIL "got $HTTP_CODE (want 401)"
  http_req 10 -X POST "http://127.0.0.1:$AGENT_PORT/v1/solve" -H 'Content-Type: application/json' -d '{}'
  [ "$HTTP_CODE" = "401" ] && record "HTTP-NOTOKEN-solve" PASS "401 as required" \
    || record "HTTP-NOTOKEN-solve" FAIL "got $HTTP_CODE (want 401)"
  http_req 10 -X POST "http://127.0.0.1:$AGENT_PORT/v1/solve" -H "$(tok_hdr "$FPGACHINA_TOKEN")" \
    -H 'Content-Type: application/json' -d '{}'
  [ "$HTTP_CODE" = "400" ] && record "HTTP-MISSING-FIELDS" PASS "400 $(printf '%s' "$HTTP_BODY" | head -c 70)" \
    || record "HTTP-MISSING-FIELDS" FAIL "got $HTTP_CODE (want 400)"
  http_req 10 -X POST "http://127.0.0.1:$AGENT_PORT/v1/solve" -H "$(tok_hdr "$FPGACHINA_TOKEN")" \
    -H 'Content-Type: application/json' -d '{not json'
  [ "$HTTP_CODE" = "400" ] && record "HTTP-BAD-JSON" PASS "400" || record "HTTP-BAD-JSON" FAIL "got $HTTP_CODE (want 400)"
  http_req 10 -X POST "http://127.0.0.1:$AGENT_PORT/v1/solve" -H "$(tok_hdr "$FPGACHINA_TOKEN")" \
    -H 'Content-Type: application/json' -d '{"task_id":"d0","prompt":"x","deadline_s":0}'
  [ "$HTTP_CODE" = "400" ] && record "HTTP-DEADLINE-ZERO" PASS "400" || record "HTTP-DEADLINE-ZERO" FAIL "got $HTTP_CODE (want 400)"
  http_req 10 -X POST "http://127.0.0.1:$AGENT_PORT/v1/solve" -H "$(tok_hdr "$FPGACHINA_TOKEN")" \
    -H 'Content-Type: application/json' -d '{"task_id":"m0","prompt":"x","mode":"bogus","deadline_s":5}'
  [ "$HTTP_CODE" = "400" ] && record "HTTP-BAD-MODE" PASS "400" || record "HTTP-BAD-MODE" FAIL "got $HTTP_CODE (want 400)"
  python3 -c 'import json;print(json.dumps({"task_id":"big","prompt":"x"*1200000}))' > "$WORK/big.json"
  http_req 20 -X POST "http://127.0.0.1:$AGENT_PORT/v1/solve" -H "$(tok_hdr "$FPGACHINA_TOKEN")" \
    -H 'Content-Type: application/json' --data-binary "@$WORK/big.json"
  [ "$HTTP_CODE" = "400" ] && record "HTTP-OVERSIZE-BODY" PASS "400 (1.2 MB rejected)" \
    || record "HTTP-OVERSIZE-BODY" FAIL "got $HTTP_CODE (want 400)"
  http_req 10 -X POST "http://127.0.0.1:$AGENT_PORT/v1/solveX" -H "$(tok_hdr "$FPGACHINA_TOKEN")" \
    -H 'Content-Type: application/json' -d '{}'
  [ "$HTTP_CODE" = "404" ] && record "HTTP-UNKNOWN-PATH" PASS "404" || record "HTTP-UNKNOWN-PATH" FAIL "got $HTTP_CODE (want 404)"

  solve_to "$FPGACHINA_TOKEN" short1 "$FIXED_PROMPT" 1 "$WORK/short1.json" 30
  sh_code="$HTTP_CODE"
  local el slen
  el=$(printf '%s' "$HTTP_BODY" | python3 "$WORK/jq.py" elapsed_s)
  slen=$(printf '%s' "$HTTP_BODY" | python3 "$WORK/jq.py" --len solution)
  if [ "$sh_code" = "200" ] && python3 - "$WORK/short1.json" <<'PY'
import json, math, sys
try:
    value = json.load(open(sys.argv[1]))
    assert set(value) == {'task_id', 'solution', 'trace', 'elapsed_s'}
    assert value['task_id'] == 'short1' and isinstance(value['solution'], str)
    assert isinstance(value['elapsed_s'], (int, float)) and math.isfinite(value['elapsed_s']) and value['elapsed_s'] >= 0
except (OSError, ValueError, TypeError, AssertionError):
    raise SystemExit(1)
PY
  then
    record "HTTP-SHORT-DEADLINE" PASS "200, solution len=$slen, elapsed_s=$el (empty string is the contract answer, not an error)"
  else
    record "HTTP-SHORT-DEADLINE" FAIL "got $sh_code (want 200)"
  fi

  sec "normal solve + official judge on a fixed small task"
  local len
  len=$(solve_nonempty "$FPGACHINA_TOKEN" "accept1") \
    && record "SOLVE-NONEMPTY" PASS "non-empty RTL ($len chars)" \
    || { record "SOLVE-NONEMPTY" FAIL "$len"; write_summary; return 1; }
  if [ "$WITH_JUDGE" -eq 1 ]; then
    local jl
    if run_judge "$WORK/accept1.solution.v" > "$WORK/accept1.judge-result" && [ "$JUDGE_LEVEL" = "3" ]; then
      record "OFFICIAL-JUDGE" PASS "level L$JUDGE_LEVEL on $(basename "$FIXED_TASK"), judge sha=$JUDGE_SHA"
    else
      jl=$(cat "$WORK/accept1.judge-result")
      record "OFFICIAL-JUDGE" FAIL "level='${JUDGE_LEVEL:-none}' ($jl)"
    fi
  else
    record "OFFICIAL-JUDGE" UNTESTED "--no-judge"
  fi

  sec "concurrency, then recovery"
  ( solve_to "$FPGACHINA_TOKEN" "conc1" "$FIXED_PROMPT" "$SOLVE_DEADLINE_S" "$WORK/conc1.json"; \
    printf '%s' "$HTTP_CODE" > "$WORK/conc1.code" ) &
  local b1=$!
  ( solve_to "$FPGACHINA_TOKEN" "conc2" "$FIXED_PROMPT" "$SOLVE_DEADLINE_S" "$WORK/conc2.json"; \
    printf '%s' "$HTTP_CODE" > "$WORK/conc2.code" ) &
  local b2=$!
  wait "$b1" "$b2"
  local c1 c2 l1 l2
  c1=$(cat "$WORK/conc1.code" 2>/dev/null); c2=$(cat "$WORK/conc2.code" 2>/dev/null)
  l1=$(python3 "$WORK/jq.py" --len solution < "$WORK/conc1.json" 2>/dev/null)
  l2=$(python3 "$WORK/jq.py" --len solution < "$WORK/conc2.json" 2>/dev/null)
  if [ "$c1" = "200" ] && [ "$c2" = "200" ] && { [ "${l1:-0}" -gt 0 ] || [ "${l2:-0}" -gt 0 ]; }; then
    record "CONCURRENCY" PASS "codes $c1/$c2, solution lens $l1/$l2 (>=1 non-empty)"
  else
    record "CONCURRENCY" FAIL "codes $c1/$c2, solution lens $l1/$l2"
  fi
  verify_recovery "$FPGACHINA_TOKEN" "postconc"

  sec "controlled fault injection A: agent (SIGKILL, in-flight request)"
  local apid ast tree
  apid=$(ledger_pid agent); ast=$(ledger_st agent)
  r=$(owns_check agent "$apid" "$ast")
  if [ "$r" = "OK" ] && fault_a_inflight_snapshot "$FPGACHINA_TOKEN" "$apid" && [ "$(owns_check agent "$apid" "$ast")" = "OK" ]; then
    record "FAULT-A-OWNERSHIP" PASS "agent pid=$apid starttime=$ast verified (cmdline+exe+port+starttime)"
    tree="$INFLIGHT_TREE"
    kill -9 "$apid" 2>/dev/null
    inflight_reap
    record "FAULT-A-KILL" INFO "SIGKILL sent to verified pid $apid; in-flight request code=$(cat "$WORK/inflight.code" 2>/dev/null)"
    local ok=0 npid nst
    for i in $(seq 1 $((RESTART_WAIT_S/2))); do
      sleep 2; refresh_started_pids
      npid=$(ledger_pid agent); nst=$(ledger_st agent)
      if [ -n "$npid" ] && [ "$npid" != "$apid" ] && wait_agent_ready "$FPGACHINA_TOKEN" 2; then ok=1; break; fi
      budget_exceeded && break
    done
    if [ "$ok" -eq 1 ]; then
      record "FAULT-A-RESTART" PASS "new agent pid=$npid starttime=$nst (old $apid)"
      r=$(owns_check agent "$npid" "$nst")
      [ "$r" = "OK" ] && record "FAULT-A-NEW-OWNERSHIP" PASS "restarted agent verified" \
        || record "FAULT-A-NEW-OWNERSHIP" FAIL "restarted agent not verifiable: $r"
    else
      record "FAULT-A-RESTART" FAIL "no new verified agent within ${RESTART_WAIT_S}s"
    fi
    local left; left=$(tree_survivors "$tree")
    if [ -z "$left" ]; then
      record "FAULT-A-LEFTOVERS" PASS "no surviving descendants after SIGKILL"
    else
      record "FAULT-A-LEFTOVERS" INFO "orphans after SIGKILL (expected, REPORT.md L171):$left (left in place)"
    fi
    residue_step AFTER-FAULT-A "$EDA_BASE"
    verify_recovery "$FPGACHINA_TOKEN" "postagent"
  else
    inflight_reap
    record "FAULT-A-OWNERSHIP" UNTESTED "ownership or in-flight work not provable: $r"
    record "FAULT-A-RESTART" UNTESTED "not injected"
    record "FAULT-A-LEFTOVERS" UNTESTED "not injected"
  fi

  sec "controlled fault injection B: model"
  local mpid mst
  mpid=$(ledger_pid model); mst=$(ledger_st model)
  if [ -n "$mpid" ] && [ "$mpid" != "$EXTERNAL_MODEL_PID" ]; then
    r=$(owns_check model "$mpid" "$mst")
    if [ "$r" = "OK" ]; then
      record "FAULT-B-OWNERSHIP" PASS "model pid=$mpid starttime=$mst verified"
      kill -9 "$mpid" 2>/dev/null
      record "FAULT-B-KILL" INFO "SIGKILL sent to verified pid $mpid"
      local ok=0 npid="" nst="" nident=""
      for i in $(seq 1 $((RESTART_WAIT_S/2))); do
        sleep 2; refresh_started_pids
        npid=$(ledger_pid model); nst=$(ledger_st model); nident=$(model_identity)
        if [ -n "$npid" ] && [ "$npid" != "$mpid" ] && [ "${nident%%|*}" = "$MODEL_NAME" ]; then ok=1; break; fi
        budget_exceeded && break
      done
      if [ "$ok" -eq 1 ]; then
        record "FAULT-B-RESTART" PASS "new model pid=$npid id=${nident%%|*} (old $mpid)"
        r=$(owns_check model "$npid" "$nst")
        [ "$r" = "OK" ] && record "FAULT-B-NEW-OWNERSHIP" PASS "restarted model verified" \
          || record "FAULT-B-NEW-OWNERSHIP" FAIL "restarted model not verifiable: $r"
      else
        record "FAULT-B-RESTART" FAIL "model not back within ${RESTART_WAIT_S}s"
      fi
      residue_step AFTER-FAULT-B "$EDA_BASE"
      verify_recovery "$FPGACHINA_TOKEN" "postmodel"
    else
      record "FAULT-B-OWNERSHIP" UNTESTED "refused, ownership not provable: $r"
      record "FAULT-B-RESTART" UNTESTED "not injected"
    fi
  elif [ -n "$EXTERNAL_MODEL_PID" ]; then
    record "FAULT-B-RESTART" UNTESTED "pre-existing model pid $EXTERNAL_MODEL_PID is shared; never signalled by this test"
  else
    record "FAULT-B-RESTART" UNTESTED "no model owned by this run and none pre-existed"
  fi

  sec "SIGTERM contract (${TERM_LIMIT_S}s, API_CONTRACT.md L287), in-flight request"
  local spid sst tree2 t0 tterm
  spid=$(ledger_pid agent); sst=$(ledger_st agent)
  r=$(owns_check agent "$spid" "$sst")
  if [ "$r" = "OK" ] && fault_a_inflight_snapshot "$FPGACHINA_TOKEN" "$spid" && [ "$(owns_check agent "$spid" "$sst")" = "OK" ]; then
    tree2="$INFLIGHT_TREE"
    t0=$(date +%s%N)
    kill -TERM "$spid" 2>/dev/null
    tterm=""
    while :; do
      if ! proc_alive "$spid"; then tterm=$(( ($(date +%s%N) - t0) / 1000000 )); break; fi
      [ $(( ($(date +%s%N) - t0) / 1000000 )) -gt $((TERM_LIMIT_S * 1000 + 5000)) ] && break
      sleep 0.1
    done
    if [ -n "$tterm" ] && [ "$tterm" -le $((TERM_LIMIT_S * 1000)) ]; then
      record "SIGTERM-EXIT" PASS "exited after ${tterm} ms (limit ${TERM_LIMIT_S}s)"
    elif [ -n "$tterm" ]; then
      record "SIGTERM-EXIT" FAIL "exited after ${tterm} ms (limit ${TERM_LIMIT_S}s)"
    else
      record "SIGTERM-EXIT" FAIL "still alive after the limit"
      [ "$(owns_check agent "$spid" "$sst")" = "OK" ] && kill -9 "$spid" 2>/dev/null
    fi
    inflight_reap
    local ok=0 npid nst
    for i in $(seq 1 $((RESTART_WAIT_S/2))); do
      sleep 2; refresh_started_pids
      npid=$(ledger_pid agent); nst=$(ledger_st agent)
      if [ -n "$npid" ] && [ "$npid" != "$spid" ] && wait_agent_ready "$FPGACHINA_TOKEN" 2; then ok=1; break; fi
      budget_exceeded && break
    done
    [ "$ok" -eq 1 ] && record "SIGTERM-RESTART" PASS "guardian restarted agent pid=$npid" \
      || record "SIGTERM-RESTART" FAIL "no restart within ${RESTART_WAIT_S}s"
    local left2; left2=$(tree_survivors "$tree2")
    [ -z "$left2" ] && record "SIGTERM-LEFTOVERS" PASS "no surviving descendants after SIGTERM" \
      || record "SIGTERM-LEFTOVERS" FAIL "surviving descendants after SIGTERM:$left2"
    residue_step AFTER-SIGTERM "$EDA_BASE"
    verify_recovery "$FPGACHINA_TOKEN" "postsigterm"
  else
    inflight_reap
    record "SIGTERM-EXIT" UNTESTED "ownership or in-flight work not provable: $r"
    record "SIGTERM-RESTART" UNTESTED "not injected"
    record "SIGTERM-LEFTOVERS" UNTESTED "not injected"
  fi

  sec "end state"
  local gp gs entryafter
  gp=$(ledger_pid guardian); gs=$(ledger_st guardian)
  r=$(owns_check guardian "$gp" "$gs")
  printf 'guardian pid=%s starttime=%s ownership=%s\n' "${gp:-none}" "${gs:-none}" "$r"
  if [ "$END_MODE" = "keep-guardian" ]; then
    if [ "$r" = "OK" ]; then
      record "END-GUARDIAN" PASS "guardian left running and verified (pid=$gp)"
      LIVE_LIST=1
    else
      record "END-GUARDIAN" FAIL "keep-guardian requested but guardian not verifiable: $r"
    fi
  else
    record "END-GUARDIAN" INFO "restore mode: this run's guardian is stopped in cleanup; no standing-by claim"
  fi
  if [ -n "$EXTERNAL_MODEL_PID" ]; then
    proc_alive "$EXTERNAL_MODEL_PID" \
      && record "END-EXTERNAL-MODEL" PASS "pre-existing model pid $EXTERNAL_MODEL_PID alive and untouched" \
      || record "END-EXTERNAL-MODEL" FAIL "pre-existing model pid $EXTERNAL_MODEL_PID is gone"
  fi
  entryafter=$(sha256sum "$ENTRY_DEPLOY" 2>/dev/null | awk '{print $1}')
  [ "$entryafter" = "$ENTRY_DEPLOY_SHA" ] \
    && record "END-ENTRY-UNCHANGED" PASS "entry hash unchanged during the run" \
    || record "END-ENTRY-UNCHANGED" FAIL "entry changed: $ENTRY_DEPLOY_SHA -> $entryafter"
  residue_step END "$EDA_BASE"
  printf 'final /v1/models: %s\n' "$(model_identity)"
  health_probe "$FPGACHINA_TOKEN" >/dev/null 2>&1
  printf 'final health: HTTP %s %s\n' "$HTTP_CODE" "${HTTP_BODY:0:200}"
  record "END-REBOOT-AUTOSTART" UNTESTED "full-machine reboot autostart not tested (no reboot performed)"
  write_summary
  [ "$N_FAIL" -gt 0 ] && return 1
  [ "$N_UNTESTED" -gt 0 ] && return 2
  return 0
}

# ---------------------------------------------------------------- summary / cleanup
write_summary() {
  local model_id; model_id=$(model_identity)
  local verdict="NOT_AN_ACCEPTANCE"
  if [ "$MODE" = "execute" ]; then
    if [ "$N_FAIL" -gt 0 ]; then verdict="FAIL"
    elif [ "$N_UNTESTED" -gt 0 ]; then verdict="INCOMPLETE_UNTESTED"
    else verdict="PASS"; fi
  elif [ "$MODE" = "self-test" ]; then verdict="UNIT_TEST_ONLY"
  fi
  DV_SELF_SHA="$SELF_SHA" DV_MODE="$MODE" DV_END_MODE="$END_MODE" DV_STAMP="$STAMP" \
  DV_FIXED_TASK="$FIXED_TASK" DV_JUDGE="$JUDGE" \
  DV_PASS="$N_PASS" DV_FAIL="$N_FAIL" DV_UNTESTED="$N_UNTESTED" DV_INFO="$N_INFO" \
  DV_ENTRY_DEPLOY="$ENTRY_DEPLOY" DV_ENTRY_DEPLOY_SHA="$ENTRY_DEPLOY_SHA" \
  DV_ENTRY_SUBMISSION="$ENTRY_SUBMISSION" DV_ENTRY_SUBMISSION_SHA="$ENTRY_SUBMISSION_SHA" \
  DV_JUDGE_SHA="$JUDGE_SHA" DV_EXT_MODEL_PID="$EXTERNAL_MODEL_PID" \
  python3 - "$JSON_OUT" "$verdict" "$model_id" \
    "$(ledger_pid guardian)" "$(ledger_pid agent)" "$(ledger_pid model)" <<'PY'
import json, sys
out, verdict, model_id = sys.argv[1], sys.argv[2], sys.argv[3]
gpid, apid, mpid = sys.argv[4], sys.argv[5], sys.argv[6]
def env(k, d=""):
    import os
    return os.environ.get(k, d)
doc = {
  "script_sha256": env("DV_SELF_SHA"),
  "mode": env("DV_MODE"),
  "end_mode": env("DV_END_MODE"),
  "generated_utc": env("DV_STAMP"),
  "steps": {"pass": int(env("DV_PASS", "0")), "fail": int(env("DV_FAIL", "0")),
            "untested": int(env("DV_UNTESTED", "0")), "info": int(env("DV_INFO", "0"))},
  "entry_deployed": env("DV_ENTRY_DEPLOY"),
  "entry_deployed_sha256": env("DV_ENTRY_DEPLOY_SHA"),
  "entry_submission": env("DV_ENTRY_SUBMISSION"),
  "entry_submission_sha256": env("DV_ENTRY_SUBMISSION_SHA"),
  "judge": env("DV_JUDGE"),
  "judge_sha256": env("DV_JUDGE_SHA"),
  "fixed_task": env("DV_FIXED_TASK"),
  "pre_existing_model_pid": env("DV_EXT_MODEL_PID"),
  "guardian_pid": gpid,
  "agent_pid": apid,
  "model_pid": mpid,
  "final_models_identity": model_id,
  "acceptance_verdict": verdict,
  "note": "A PASS verdict covers only the items actually tested in this run; untested items are listed as UNTESTED in steps.txt. Never read this file as proof of anything that is marked UNTESTED."
}
open(out, "w").write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
PY
  printf 'summary written: %s\n' "$JSON_OUT"
}

cleanup() {
  local rc=$? r
  if [ "$MODE" = "self-test" ]; then st_sweep; fi
  if [ "$MODE" = "execute" ] && [ "$LIVE_LIST" != "1" ]; then
    local gp gs ap as mp ms
    gp=$(ledger_pid guardian); gs=$(ledger_st guardian)
    if [ -n "$gp" ]; then
      r=$(owns_check guardian "$gp" "$gs")
      if [ "$r" = "OK" ]; then
        printf 'cleanup: stopping this run'"'"'s guardian pid=%s\n' "$gp"
        kill -TERM "$gp" 2>/dev/null; sleep 1
        [ "$(owns_check guardian "$gp" "$gs")" = "OK" ] && kill -9 "$gp" 2>/dev/null
      else
        printf 'cleanup: guardian pid=%s is not provably ours (%s); left alone\n' "$gp" "$r"
      fi
    fi
    ap=$(ledger_pid agent); as=$(ledger_st agent)
    if [ -n "$ap" ]; then
      r=$(owns_check agent "$ap" "$as")
      if [ "$r" = "OK" ]; then
        printf 'cleanup: stopping the agent this run started pid=%s\n' "$ap"
        kill -TERM "$ap" 2>/dev/null; sleep 1
        [ "$(owns_check agent "$ap" "$as")" = "OK" ] && kill -9 "$ap" 2>/dev/null
      fi
    fi
    mp=$(ledger_pid model); ms=$(ledger_st model)
    if [ -n "$mp" ] && [ "$mp" != "$EXTERNAL_MODEL_PID" ]; then
      r=$(owns_check model "$mp" "$ms")
      if [ "$r" = "OK" ]; then
        printf 'cleanup: stopping the model this run started pid=%s\n' "$mp"
        kill -TERM "$mp" 2>/dev/null; sleep 1
        [ "$(owns_check model "$mp" "$ms")" = "OK" ] && kill -9 "$mp" 2>/dev/null
      fi
    fi
    if [ -n "$EXTERNAL_MODEL_PID" ] && ! proc_alive "$EXTERNAL_MODEL_PID"; then
      printf 'cleanup: WARNING pre-existing model pid %s is not alive\n' "$EXTERNAL_MODEL_PID"
    fi
  fi
  exit "$rc"
}

# ---------------------------------------------------------------- main
[ -f "$0" ] && SELF_SHA=$(sha256sum "$0" 2>/dev/null | awk '{print $1}')
trap cleanup EXIT

case "$MODE" in
  self-test) self_test; exit $? ;;
  dry-run)   dry_run;   exit $? ;;
  execute)   execute;   exit $? ;;
esac
