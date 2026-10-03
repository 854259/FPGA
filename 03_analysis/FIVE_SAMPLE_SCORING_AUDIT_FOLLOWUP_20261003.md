# 五样本评分审查：修复后独立复核补充

日期：2026-10-03。性质：只读静态复核；本轮仅新增此报告。

## 结论与核对版本

认可工程方对原三项评分缺陷的回应：空答保留为 L0、完整 verdict 保留环境失败分类、pass@5 使用最高可计分系数，均已在当前源码中修复。缺题与少采样也已有显式台账。仍有两项独立的状态与判定进程风险，下文给出触发条件；它们不等于原三项缺陷仍未修复，也不证明实际实验已经受到影响。

核对分支：`feat/official-rtl-contract`；固定 HEAD：`64abcf5f0dd523e92ec2ecea6b24e0113fba4185`。

核对对象的 Git blob SHA：

- `bench/five_sample_quality.py`：`eabb4149a51546b9f8947bf8265bd33abb3159c8`。
- `tests/test_scoring_convention.py`：`85f64d99b26fc9e53f90db3c3b7a39486bdbdb3b`。
- `official_reference/selftest/score.py`：`b9df8ed09adc18e5193d1c5ccc07e564a3ff04d0`。
- `official_reference/selftest/judge.py`：`d89997aa008756e3955ee519f325c34f601b6b5f`。

评分依据是仓库 [UPSTREAM.json](https://github.com/854259/FPGA/blob/64abcf5f0dd523e92ec2ecea6b24e0113fba4185/04_project/amd_rtl_agent/official_reference/UPSTREAM.json) 固定的上游提交 `afd135e7ba5f6ec4c6d77e7c927c894327537801` 及其仓内副本；本报告没有核验上游最新版本。

[原审计](https://github.com/854259/FPGA/blob/64abcf5f0dd523e92ec2ecea6b24e0113fba4185/03_analysis/FIVE_SAMPLE_SCORING_AUDIT_20261003.md) 针对修复前 `41dec5aa8c9d99096eff5538cbea292aea914d27`；[工程回应](https://github.com/854259/FPGA/blob/64abcf5f0dd523e92ec2ecea6b24e0113fba4185/03_analysis/FIVE_SAMPLE_SCORING_AUDIT_RESPONSE_20261003.md) 将五样本评分审查与另一份 `verify_full156.py` 审查分开记录，这一更正成立。本报告保留原审计作为历史证据，不重写原文，也不复核另一工具的修复结论。

## 已静态闭环

| 原发现 | 当前接线与判断 |
|---|---|
| 空答／请求失败被过滤，缩小 pass@1 分母 | [L194–207](https://github.com/854259/FPGA/blob/64abcf5f0dd523e92ec2ecea6b24e0113fba4185/04_project/amd_rtl_agent/bench/five_sample_quality.py#L194-L207) 对空 solution 仍调用 judge，并追加其 verdict；固定 judge 将空解判为 L0。未再用 HTTP 状态或空答过滤聚合输入。 |
| pass@5 被替换为“任一 L3” | [L239–244](https://github.com/854259/FPGA/blob/64abcf5f0dd523e92ec2ecea6b24e0113fba4185/04_project/amd_rtl_agent/bench/five_sample_quality.py#L239-L244) 调用固定 `official.summarize()`；[score L73–105](https://github.com/854259/FPGA/blob/64abcf5f0dd523e92ec2ecea6b24e0113fba4185/04_project/amd_rtl_agent/official_reference/selftest/score.py#L73-L105) 在可计分样本中取最高系数，再按计分题平均。旧二元指标在 [L257–267](https://github.com/854259/FPGA/blob/64abcf5f0dd523e92ec2ecea6b24e0113fba4185/04_project/amd_rtl_agent/bench/five_sample_quality.py#L257-L267) 另名 `any_l3`。 |
| 聚合丢失 tool_error，环境失败计为零分 | [L202–210](https://github.com/854259/FPGA/blob/64abcf5f0dd523e92ec2ecea6b24e0113fba4185/04_project/amd_rtl_agent/bench/five_sample_quality.py#L202-L210) 保留完整 verdict；固定 summarize 单列排除 tool_error，整题全环境失败标为不计分。 |
| 缺题／少采样缺少显式完成性记录 | [L172–187](https://github.com/854259/FPGA/blob/64abcf5f0dd523e92ec2ecea6b24e0113fba4185/04_project/amd_rtl_agent/bench/five_sample_quality.py#L172-L187) 记录预期格数与缺题，[L232–234](https://github.com/854259/FPGA/blob/64abcf5f0dd523e92ec2ecea6b24e0113fba4185/04_project/amd_rtl_agent/bench/five_sample_quality.py#L232-L234) 检查尝试格数，[L281](https://github.com/854259/FPGA/blob/64abcf5f0dd523e92ec2ecea6b24e0113fba4185/04_project/amd_rtl_agent/bench/five_sample_quality.py#L281) 不完整返回 2。此处“完整”的含义仍限于尝试齐全，见下一节。 |

四个单题算例与固定评分函数的定义一致：

| 五个样本 | pass@1 | pass@5 | 可计分／排除 |
|---|---:|---:|---:|
| 1×L3 + 4×空答（L0） | 0.2 | 1.0 | 5／0 |
| 5×L1 | 0.2 | 0.2 | 5／0 |
| 5×L2 | 0.7 | 0.7 | 5／0 |
| 1×L3 + 4×环境失败 | 1.0 | 1.0 | 1／4 |

这是静态算例核对，不是本轮执行结果。工程方报告 22 项测试通过；本轮读取了测试源码和回应文件，未运行测试，未独立重新证明“通过”。

## 残余一：尝试完成与可比较状态尚未分开

[L232–234](https://github.com/854259/FPGA/blob/64abcf5f0dd523e92ec2ecea6b24e0113fba4185/04_project/amd_rtl_agent/bench/five_sample_quality.py#L232-L234) 的 `complete` 只检查 `attempted == expected_cells` 且 `missing_tasks` 为空；[L269–271](https://github.com/854259/FPGA/blob/64abcf5f0dd523e92ec2ecea6b24e0113fba4185/04_project/amd_rtl_agent/bench/five_sample_quality.py#L269-L271) 将它写入 JSON，[L281](https://github.com/854259/FPGA/blob/64abcf5f0dd523e92ec2ecea6b24e0113fba4185/04_project/amd_rtl_agent/bench/five_sample_quality.py#L281) 据此返回 0。

静态构造：默认 8 题×2 模式×5 样本共 80 格，若 `attempted=80`、`expected_cells=80`、`tool_error=80`、`graded=0`、`missing_tasks=[]`，当前条件仍得到 `complete=true` 和退出码 0。两个模式的 `scored_tasks` 都为 0，汇总的零分只是兜底，不能用于模型比较。此例未在本轮运行，也未证明实际产物处于该状态。

源码已经在 [L242–247](https://github.com/854259/FPGA/blob/64abcf5f0dd523e92ec2ecea6b24e0113fba4185/04_project/amd_rtl_agent/bench/five_sample_quality.py#L242-L247) 报告计分题数及环境失败，并在 [L253–255](https://github.com/854259/FPGA/blob/64abcf5f0dd523e92ec2ecea6b24e0113fba4185/04_project/amd_rtl_agent/bench/five_sample_quality.py#L253-L255) 明确警告“本次结果不能用于比较”。因此问题是机器可读完成状态与比较门槛没有同步，不能称为隐瞒环境失败。只读取 `complete` 或退出码的自动消费者可能误把尝试齐全当作可用实验。

最小建议：保留尝试台账，显式区分 `attempts_complete`、每模式／每题的 `scored_coverage` 与 `comparable`，并记录不可比较原因；任一模式无有效成绩时明确 `comparable=false`。再由工程方规定用于验收的退出码策略，使自动消费者能识别“尝试完成但不可比较”。覆盖率可引用现有 summary 的计分题数、有效样本与排除样本，不必另造评分口径。

不能把“出现任意 tool_error”一律改成实验失败：固定评分函数允许排除环境失败后使用其余成绩。需要公开覆盖范围、明确比较条件，而不是把已排除样本重新计为模型零分。

## 残余二：新 verdict 可解析时仍忽略非零退出

[run_judge L125–138](https://github.com/854259/FPGA/blob/64abcf5f0dd523e92ec2ecea6b24e0113fba4185/04_project/amd_rtl_agent/bench/five_sample_quality.py#L125-L138) 已清理旧输出目录，并在无文件或 JSON 不可解析时返回 tool_error，这些改进应予认可。剩余路径是：本轮进程新写出可解析的成绩 JSON 后退出非零；函数仍直接返回 JSON，`proc.returncode` 只在无文件分支进入错误说明。

静态构造：新 verdict 含 `level=3`、`coefficient=1.0` 且无 tool_error，随后进程退出 1，当前接线仍可能将其计为有效 L3。这不是旧 verdict 复用问题，也没有证据表明固定 judge 或某次实际实验已经触发这一组合。

最小建议：保留退出码与判定输出证据，按固定 judge 的退出契约决定结果是否可采纳。当前固定 [judge 入口](https://github.com/854259/FPGA/blob/64abcf5f0dd523e92ec2ecea6b24e0113fba4185/04_project/amd_rtl_agent/official_reference/selftest/judge.py) 正常写出结果后返回 0；若新结果伴随非零退出，应作为判定异常明确分类，原 JSON 与日志仍保留供追查。若将来确有可接受的非零状态，应列出明确规则，不能仅凭 JSON 可解析就默认成功。

## 测试证据与最小补充

[测试 L147–186](https://github.com/854259/FPGA/blob/64abcf5f0dd523e92ec2ecea6b24e0113fba4185/04_project/amd_rtl_agent/tests/test_scoring_convention.py#L147-L186) 覆盖无 verdict、旧目录清理、坏 JSON，未覆盖“新有效 verdict + 非零退出”。[L192–215](https://github.com/854259/FPGA/blob/64abcf5f0dd523e92ec2ecea6b24e0113fba4185/04_project/amd_rtl_agent/tests/test_scoring_convention.py#L192-L215) 的台账测试重写布尔公式，未覆盖全环境失败时实际主流程的 JSON 状态、警告与退出码。

[L81–87](https://github.com/854259/FPGA/blob/64abcf5f0dd523e92ec2ecea6b24e0113fba4185/04_project/amd_rtl_agent/tests/test_scoring_convention.py#L81-L87) 已覆盖评分函数对全环境失败题的排除；不能说该边界完全没有测试。缺口在主流程完成／比较状态的行为验证。建议工程方只补上述两个针对性行为用例，并同时核对输出证据与状态字段，避免只复写实现公式。

## 意义、验证范围与回退

此次闭环确认评分转换已有正确接线，使后续复用原始 verdict 重建摘要具有明确口径。两项建议分别减少自动验收误读和判定异常被采纳的风险；修改退出码或状态字段前，应核对已有消费者的兼容性，不改变固定官方评分函数。

本轮只读取固定版本源码、测试定义与文档，未修改代码、运行脚本或测试、部署、连接服务器、重判候选或重建真实摘要。实际受影响样本数与分数变化未知，不能由本报告推导 H3 无效、历史 44 题可靠泛化、瑕疵影响对称或旧翻转比例的统计模型。默认 80 次子集也不能写成完成 1560 次协议。

交付仅为这一份脱敏新增报告；原报告与工程回应保留。最小下一步由工程方处理两项状态／进程建议及对应行为用例，再在获准运行环境复核真实产物。若撤回本报告，可单独 revert 本次文档提交，不涉及工程修复或已有实验。
