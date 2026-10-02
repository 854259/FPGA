#!/bin/bash
# ============================================================================
# 状态：**未执行**（2026-10-03 分析预判为负，故未运行）
#
# 见 03_analysis/25_输出长度是特征不是缺陷_20261003.md：
#   - 最长单次输出 >=2000 token 的 5 道题里 4 道是 L3
#   - --reasoning off 下注释即模型的思考过程
#   - 压制注释很可能打掉那 4 道 L3，只为救 Prob147 一道 → 预期净亏约 3 道题
#   - 省下约 3.2 小时模型槽
#
# 脚本本身完整可用，未删除；若判断改变可直接执行。
# ============================================================================
# 假设 H 的配对实验：技能只增"输出预算"一句（8 规则版）
#
# 单变量：技能文本 +1 行（453->506 字符，f4c4c8e2 -> 3c7b2f2d）。模型、参数、题集、runtime 全不动。
# 对照：刚跑完的新基线（runtime 22e32251 + 7 规则技能）。
#
# 判定标准（先写死，避免事后找理由）：
#   净收益 = (新 agent 题集得分 - 基线 agent 题集得分)，分母 156
#   > 0 才采纳；<= 0 则还原技能并记录为否定结果。
set -u

K=/workspace/team/tasks/autodl-rtl-kit/project
SKILL=$K/submission/skill/rtl-generation/SKILL.md
VARIANT=/workspace/team/runs/fpga_owner/skill_variant_8rules.md
BASE=/workspace/team/runs/fpga_owner/full156_declfix_20261003
OUT=/workspace/team/runs/fpga_owner/full156_skill8_20261003
BK=/workspace/team/runs/fpga_owner/skill_backup_20261003

mkdir -p "$BK" "$OUT/scratch"

OLD=$(sha256sum "$SKILL" | cut -c1-16)
NEW=$(sha256sum "$VARIANT" | cut -c1-16)
echo "技能 旧版(7规则): $OLD  期望 f4c4c8e2d97ec476"
echo "技能 新版(8规则): $NEW  期望 3c7b2f2dfefea02e"
if [ "$OLD" != "f4c4c8e2d97ec476" ]; then echo "  ✗ 旧版哈希不符，放弃"; exit 1; fi
if [ "$NEW" != "3c7b2f2dfefea02e" ]; then echo "  ✗ 变体哈希不符，放弃"; exit 1; fi

cp "$SKILL" "$BK/SKILL.7rules.$OLD.md"
cp "$VARIANT" "$SKILL"
chmod 644 "$SKILL"
NOW=$(sha256sum "$SKILL" | cut -c1-16)
echo "  换入后: $NOW"
if [ "$NOW" != "$NEW" ]; then echo "  ✗ 换入失败"; exit 1; fi
echo "  ✓ 哈希一致"

restore() {
  echo
  echo "[trap] 还原技能为 7 规则版"
  cp "$BK/SKILL.7rules.$OLD.md" "$SKILL"
  chmod 644 "$SKILL"
  R=$(sha256sum "$SKILL" | cut -c1-16)
  if [ "$R" = "$OLD" ]; then echo "[trap] ✓ 已还原 ($R)"; else echo "[trap] ✗ 还原失败，当前 $R"; fi
  /workspace/team/slot.sh release owner_skill8 2>/dev/null
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
echo "[$(date -u +%H:%M:%SZ)] 开始 8 规则技能全量配对"
cd "$K"
python3 -B official_eval.py --tasks bench/tasks_veval --out "$OUT/full" --samples 1 --deadline 300
echo "[$(date -u +%H:%M:%SZ)] 结束 rc=$?"

S=$OUT/full/graded_summary.json
[ -f "$S" ] || { echo "  ✗ 无 graded_summary"; exit 1; }

echo
echo "=== 8 规则结果 ==="
python3 -c "
import json
d = json.load(open('$S'))
for m, s in d['modes'].items():
    print('  %-9s set=%.4f levels=%s' % (m, s['set_score'], s['level_counts']))
"

echo
echo "=== 与 7 规则基线逐题对比 ==="
python3 /workspace/team/compare_repeatability.py \
  "$BASE/full/results" "$OUT/full/results" --json "$OUT/diff.json"

echo
echo "=== 先写死的判定标准 ==="
python3 -c "
import json
def score(p):
    d = json.load(open(p))
    return d['modes']['agent']['set_score'], d['modes']['baseline']['set_score']
a8, b8 = score('$S')
a7, b7 = score('$BASE/full/graded_summary.json')
print('  7 规则 agent: %.4f   8 规则 agent: %.4f   差 %+.4f' % (a7, a8, a8 - a7))
print('  7 规则 增益 : %.4f   8 规则 增益 : %.4f' % (a7/b7 if b7 else 0, a8/b8 if b8 else 0))
print()
print('  判定:', '✅ 采纳（净收益为正）' if a8 > a7 else '❌ 不采纳（净收益 <= 0），已还原技能')
"

echo
echo "=== 关键题的级别 ==="
python3 -c "
import json, os
for t in ('Prob147_circuit10', 'Prob058_alwaysblock2', 'Prob082_lfsr32', 'Prob134_2014_q3c', 'Prob144_conwaylife', 'Prob156_review2015_fancytimer'):
    def lv(root):
        p = os.path.join(root, 'agent.%s.s0.json' % t)
        return json.load(open(p))['level'] if os.path.isfile(p) else None
    print('  %-32s 7规则=L%s  8规则=L%s' % (t, lv('$BASE/full/results'), lv('$OUT/full/results')))
"
