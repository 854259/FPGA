#!/bin/bash
# /v1/solve 契约一致性测试：用契约给出的完整载荷逐字段验证
#
# 契约请求: {task_id, nonce, mode, prompt, interface, deadline_s}
# 契约响应: {task_id, solution, trace, elapsed_s}
# 关键: interface 在评测题集下为空串；做不出来返回空字符串而不是报错
set -u
K=/workspace/team/tasks/autodl-rtl-kit/project
O=/workspace/team/runs/fpga_owner/solve_contract_20261003
PORT=7863
rm -rf "$O"; mkdir -p "$O/scratch"

export PATH=/workspace/AMD/2026.1/Vivado/bin:$PATH
export LD_LIBRARY_PATH=/workspace/team/udev-stub
export XILINXD_LICENSE_FILE=/workspace/team/Xilinx.lic
export XILINX_VIVADO=/workspace/AMD/2026.1/Vivado
export LLM_BASE_URL=http://127.0.0.1:8000/v1 MODEL_NAME=Qwen3.6-27B-Q4_K_M
export RTL_PROFILE=development RTL_REPAIRS=1 RTL_MAX_TOKENS=8192 RTL_TEMPERATURE=0
export NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost
export FPGACHINA_TOKEN=solve-contract-token
export EDA_TMP=$O/scratch SELFTEST_TMP=$O/scratch

nohup python3 -B "$K/submission/agent/runtime.py" serve --port $PORT > "$O/server.log" 2>&1 &
SRV=$!
trap '[ -n "${SRV:-}" ] && kill -TERM $SRV 2>/dev/null; sleep 1; kill -9 $SRV 2>/dev/null' EXIT
for i in $(seq 1 30); do
  curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/v1/health" -H "Authorization: Bearer $FPGACHINA_TOKEN" && break
  sleep 1
done
echo "服务 PID=$SRV 端口=$PORT"

post() {  # $1=名称 $2=载荷
  local name="$1" payload="$2"
  local code
  code=$(curl -s -m 300 -o "$O/$name.json" -w '%{http_code}' \
    -X POST "http://127.0.0.1:$PORT/v1/solve" \
    -H "Authorization: Bearer $FPGACHINA_TOKEN" \
    -H 'Content-Type: application/json' --data-binary "$payload")
  echo "$name|$code" >> "$O/results.txt"
}

: > "$O/results.txt"
PROMPT=$(python3 -c "import json;print(json.dumps(open('$K/bench/tasks_veval/Prob001_zero/prompt.txt',encoding='utf-8').read()))")
SHORT=$(python3 -c "import json;print(json.dumps(open('$K/bench/tasks_veval/Prob001_zero/prompt.txt',encoding='utf-8').read()[:120]))")

echo
echo "=== 1) 契约完整载荷，interface 为空串（评测题集的实际情况）==="
post full_empty_iface "{\"task_id\":\"eval-0001\",\"nonce\":\"T042-eval-0001-1-1763251200123456789\",\"mode\":\"agent\",\"prompt\":$PROMPT,\"interface\":\"\",\"deadline_s\":300}"

echo "=== 2) mode=baseline ==="
post mode_baseline "{\"task_id\":\"eval-0002\",\"nonce\":\"n2\",\"mode\":\"baseline\",\"prompt\":$PROMPT,\"interface\":\"\",\"deadline_s\":300}"

echo "=== 3) 省略 nonce 与 mode（可选字段）==="
post minimal "{\"task_id\":\"eval-0003\",\"prompt\":$PROMPT,\"deadline_s\":300}"

echo "=== 4) 缺 task_id（应 400）==="
post no_task_id "{\"prompt\":$PROMPT,\"deadline_s\":300}"

echo "=== 5) 非法 JSON（应 400）==="
post bad_json "{not json"

echo "=== 6) interface 非空 ==="
post with_iface "{\"task_id\":\"eval-0006\",\"prompt\":$SHORT,\"interface\":\"module TopModule (output zero);\",\"deadline_s\":300}"

echo "=== 7) deadline_s 极小（应仍返回 200 与空解答，不报错）==="
post tiny_deadline "{\"task_id\":\"eval-0007\",\"prompt\":$SHORT,\"interface\":\"\",\"deadline_s\":1}"

echo "=== 8) 无 token（应 401）==="
code=$(curl -s -o /dev/null -m 10 -w '%{http_code}' -X POST "http://127.0.0.1:$PORT/v1/solve" \
  -H 'Content-Type: application/json' -d '{}')
echo "  no_token|$code" >> "$O/results.txt"

echo
echo "=== 逐项判定 ==="
python3 - <<'PYEOF'
import json, os
O = "/workspace/team/runs/fpga_owner/solve_contract_20261003"
expect = {
    "full_empty_iface": 200, "mode_baseline": 200, "minimal": 200,
    "no_task_id": 400, "bad_json": 400, "with_iface": 200,
    "tiny_deadline": 200, "no_token": 401,
}
REQUIRED = {"task_id", "solution", "trace", "elapsed_s"}
rows = {}
for line in open(O + "/results.txt"):
    n, c = line.strip().split("|")
    rows[n] = int(c)

for name, want in expect.items():
    got = rows.get(name)
    verdict = "✓" if got == want else "✗"
    extra = ""
    p = os.path.join(O, name + ".json")
    if got == 200 and os.path.isfile(p):
        try:
            d = json.load(open(p, encoding="utf-8"))
            keys = set(d.keys())
            if name in ("full_empty_iface", "mode_baseline", "minimal", "with_iface", "tiny_deadline"):
                if keys == REQUIRED:
                    extra = "  字段恰为契约四字段"
                else:
                    extra = "  ✗ 字段不符: %s" % sorted(keys)
                if name in ("full_empty_iface", "minimal") and d.get("task_id") != "eval-0001" and name == "full_empty_iface":
                    extra += "  ✗ task_id 未原样带回"
                if name == "full_empty_iface" and d.get("task_id") == "eval-0001":
                    extra += "  task_id 原样带回"
                if name == "tiny_deadline":
                    extra += "  solution=%d 字符（空串符合契约"%" if d.get("solution") == "" else "  ✗ 非空"
                    extra += "" if d.get("solution") == "" else "）"
                if name in ("full_empty_iface", "mode_baseline"):
                    extra += "  solution=%d 字符" % len(d.get("solution", ""))
        except Exception as e:
            extra = "  解析失败 %s" % e
    print("  %-18s HTTP %-4s 期望 %-4s %s%s" % (name, got, want, verdict, extra))
PYEOF

echo
echo "=== 服务端有无异常 ==="
grep -iE "traceback|exception" "$O/server.log" | head -3 || echo "  无"
