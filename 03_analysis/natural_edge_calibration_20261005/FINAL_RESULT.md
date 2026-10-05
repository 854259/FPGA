# FIFO62 原边沿检测 harness 校准终态

2026-10-05 使用固定 Python 3.12.14 执行既有 `raw_evidence/collect_terminal.py` 与 `raw_evidence/audit_terminal.py`，两者实际退出码均为 0。仅收齐已结束任务的文件并执行本地只读审计，没有重新运行模型、EDA 或 FIFO 任务。

## 证据绑定

| 项目 | 实际值 |
| --- | --- |
| FIFO ticket | 62，completed |
| 冻结源文件 | 11，全部 SHA 不变 |
| RUN_SPEC SHA256 | `e68dff0e4bab1a708a9617552776e3ed86adcb6d7d53aa6c004c49728707fa65` |
| 原始终态 ZIP SHA256 | `d4f104f378b90fa25841603092879cb9d3dca0fc2265ad7efc489cfbc4405ce6` |
| 原始终态 ZIP 大小 / manifest 文件数 | 1,104,792 bytes / 162 |
| 冻结 auditor SHA256 | `df76ed6037a058d7869c7d01ce14c14e1e11b20a221ccbe9c3e080ca1e10caf1` |
| 实际审计 RESULTS SHA256 | `7b61c047f308f9c76e01a5a0dedcb05b37141a95a28950b4f56d428f247d59ef` |
| 审计 schema / evidence_valid | `natural_edge_original_harness_readonly_audit_v1` / true |
| 原任务原生命令 | 7 次编译 + 7 次仿真，7 个固定控制 |
| 原任务模型调用 | 0 |
| 本次 collection / audit 模型与 EDA 调用 | 全部 0 |
| 本任务拥有进程 / 共享模型 | `owned_handles_dead=true` / `model_unchanged=true` |

## 实际结果与资格

`cvdp_copilot_edge_detector_0001` 的正确控制通过；`constant_zero`、`constant_one`、`swapped_edges`、`widened_pulse` 四项错误控制被拒绝。`reset_ignored` 错误控制实际通过，`false_acceptance=true`，因此该原 record 的 `original_harness_calibration=false`，必须保留在排除列表中。失败传播哨兵实际失败，且该哨兵 `original_harness=false`。

此结论证明原测试对本次复位错误存在漏检，不能将这些控制的通过比例当作模型正确率，也不能将该题纳入已合格的原 harness 校准证据。`eligible_for_independent_models=false`、`independent_model_tasks=0`、`adoption=false`。本轮没有独立模型质量准入、策略采用或发布。

固定实际收据保留在 `raw_evidence/TERMINAL_DOWNLOAD_RECEIPT.json`、`raw_evidence/TERMINAL_AUDIT_RECEIPT.json`；实际审计结果保留在 `raw_evidence/terminal_audit_v1/RESULTS.json`。本文件只公开元数据，不公开题面原文、RTL 或测试台。
