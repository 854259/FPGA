#!/bin/bash
# 假设 H3 的配对实验：技能补回"语法/风格"两条（规则 8、9 前半），不补语义规则（10/11）
#
# 证据来源：两版技能逐题得失的题型分析
#   状态机   : 提升 6 / 退步 1
#   组合逻辑 : 提升 6 / 退步 0
#   LFSR/移位/元胞 : 提升 0 / 退步 4   <- 损失全部集中在这里
# 假设：伤害来自"语义指令"（规则 10/11 让模型过度自我怀疑），
#       而"语法/风格指令"（规则 8/9 前半）安全且能救回位运算密集题。
#
# 单变量：技能文本 +2 行（453->628 字符，f4c4c8e2 -> 8fb63de3）。其余全不动。
# 对照：full156_declfix_20261003（runtime 22e32251 + 7 规则技能）
#   注：当前 runtime 是 cea6479c，与 22e32251 只差 health()/vram_gb()，不进评测路径。
#
# 判定标准（先写死）：agent 题集得分上涨才采纳，否则还原并记为否定结果。
set -u

K=/workspace/team/tasks/autodl-rtl-kit/project
SKILL=$K/submission/skill/rtl-generation/SKILL.md
VARIANT=/workspace/team/runs/fpga_owner/skill_variant_9rules.md
BASE=/workspace/team/runs/fpga_owner/full156_declfix_20261003
OUT=/workspace/team/runs/fpga_owner/full156_skill9_20261003
BK=/workspace/team/runs/fpga_owner/skill_backup_20261003

mkdir -p "$BK" "$OUT/scratch"

OLD=$(sha256sum "$SKILL" | cut -c1-16)
NEW=$(sha256sum "$VARIANT" | cut -c1-16)
echo "技能 旧版(7规则): $OLD  期望 f4c4c8e2d97ec476"
echo "技能 新版(9规则): $NEW  期望 8fb63de303486c9e"
[ "$OLD" = "f4c4c8e2d97ec476" ] || { echo "  ✗ 旧版哈希不符"; exit 1; }
[ "$NEW" = "8fb63de303486c9e" ] || { echo "  ✗ 变体哈希不符"; exit 1; }

cp "$SKILL" "$BK/SKILL.7rules.$OLD.md"
cp "$VARIANT" "$SKILL"
chmod 644 "$SKILL"
NOW=$(sha256sum "$SKILL" | cut -c1-16)
[ "$NOW" = "$NEW" ] && echo "  ✓ 换入成功 $NOW" || { echo "  ✗ 换入失败"; exit 1; }

restore() {
  echo
  echo "[trap] 还原技能为 7 规则版"
  cp "$BK/SKILL.7rules.$OLD.md" "$SKILL"; chmod 644 "$SKILL"
  R=$(sha256sum "$SKILL" | cut -c1-16)
  [ "$R" = "$OLD" ] && echo "[trap] ✓ 已还原 ($R)" || echo "[trap] ✗ 还原失败，当前 $R"
  /workspace/team/slot.sh release owner_skill9 2>/dev/null
}
trap restore EXIT

export PATH=/workspace/AMD/2026.1/Vivado/bin:$PATH
export LD_LIBRARY_PATH=/workspace/team/udev-stub
export XILINXD_LICENSE_FILE=/workspace/team/Xilinx.lic
export XILINX_VIVADO=/workspace/AMD/2026.1/Vivado
export LLM_BASE_URL=http://127.0.0.1:8000/v1 MODEL_NAME=Qwen3.6-27B-Q4_K_M
export RTL_PROFILE=development RTL_REPAIRS=1 RTL_MAX_TOKENS=8192 RTL_TEMPERATURE=0
export NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost
export EDA_TMP=$OUT/scratch SELFTEST_TMP=$OUT/scratch
export PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1

echo
echo "[$(date -u +%H:%M:%SZ)] 开始 9 规则技能全量配对"
cd "$K"
python3 -B official_eval.py --tasks bench/tasks_veval --out "$OUT/full" --samples 1 --deadline 300
echo "[$(date -u +%H:%M:%SZ)] 结束 rc=$?"

S=$OUT/full/graded_summary.json
[ -f "$S" ] || { echo "  ✗ 无 graded_summary"; exit 1; }

echo
echo "=== 9 规则结果 ==="
python3 -c "
import json
d = json.load(open('$S'))
for m, s in d['modes'].items():
    print('  %-9s set=%.4f levels=%s' % (m, s['set_score'], s['level_counts']))
"

echo
echo "=== 与 7 规则基线逐题对比 ==="
python3 /workspace/team/compare_repeatability.py "$BASE/full/results" "$OUT/full/results" --json "$OUT/diff.json"

echo
echo "=== 先写死的判定标准 ==="
python3 -c "
import json
def score(p):
    d = json.load(open(p)); return d['modes']['agent']['set_score'], d['modes']['baseline']['set_score']
a9, b9 = score('$S'); a7, b7 = score('$BASE/full/graded_summary.json')
print('  7 规则 agent: %.4f   9 规则 agent: %.4f   差 %+.4f' % (a7, a9, a9 - a7))
print('  7 规则 增益 : %.4f   9 规则 增益 : %.4f' % (a7/b7 if b7 else 0, a9/b9 if b9 else 0))
print()
print('  判定:', '✅ 采纳（净收益为正）' if a9 > a7 else '❌ 不采纳（净收益 <= 0），已还原技能')
"

echo
echo "=== 假设针对的题：位运算密集的 4 道 ==="
python3 -c "
import json, os
for t in ('Prob082_lfsr32','Prob086_lfsr5','Prob108_rule90','Prob115_shift18','Prob058_alwaysblock2'):
    def lv(root):
        p = os.path.join(root, 'agent.%s.s0.json' % t)
        return json.load(open(p))['level'] if os.path.isfile(p) else None
    print('  %-32s 7规则=L%s  9规则=L%s' % (t, lv('$BASE/full/results'), lv('$OUT/full/results')))
"

echo
echo "=== 守卫：状态机/组合类是否被拖累（7 规则版在此处强）==="
python3 -c "
import json, os
for t in ('Prob128_fsm_ps2','Prob140_fsm_hdlc','Prob143_fsm_onehot','Prob151_review2015_fsm',
          'Prob102_circuit3','Prob103_circuit2','Prob122_kmap4','Prob130_circuit5','Prob145_circuit8'):
    def lv(root):
        p = os.path.join(root, 'agent.%s.s0.json' % t)
        return json.load(open(p))['level'] if os.path.isfile(p) else None
    print('  %-32s 7规则=L%s  9规则=L%s' % (t, lv('$BASE/full/results'), lv('$OUT/full/results')))
"
