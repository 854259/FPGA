# FIFO63 研究复位控制校准终态

2026-10-05 使用固定 Python 3.12.14 执行既有 `raw_evidence/collect_terminal.py` 与 `raw_evidence/audit_terminal.py`。云端首次文件收齐成功后，下载连接超时；错误收据已保留，既有 helper 随后核验并恢复同一归档，下载及本地审计最终实际退出码均为 0。没有重新运行模型、EDA 或 FIFO 任务。

## 证据绑定

| 项目 | 实际值 |
| --- | --- |
| FIFO ticket | 63，completed |
| 冻结源文件 | 44，全部 SHA 不变 |
| RUN_SPEC SHA256 | `f4889422e53aa00848e567694d8df5e351c2d79713134ddd543ec638738a4bc3` |
| 原始终态 ZIP SHA256 | `1dec4736126e0de6472836a2fc5572e495d0a4febe1fc96e5ba43c9b3760de92` |
| 原始终态 ZIP 大小 / manifest 文件数 | 563,497 bytes / 251 |
| 冻结 auditor SHA256 | `084cbce2b1d32234c429f4fe4a1cc50baa9a829347cb1146259298b99a3226b0` |
| 实际审计 RESULTS SHA256 | `b7bd3816aae7f238aab39abafb138238873ca2384e5df508c3f139ebf0b79417` |
| 实际审计收据 schema | `actual_native14_terminal_audit_receipt_v1` |
| evidence_complete | true |
| 原任务原生命令 / 全局收据 | 14 次编译 + 14 次仿真 / 28 |
| 未确认原生尝试 | 0 |
| 原任务模型调用 | 0 |
| 本次 collection / audit 模型与 EDA 调用 | 全部 0 |
| 本任务拥有进程 / 共享模型 / 保护文件 | `owned_handles_dead=true` / `model_unchanged=true` / `protected_files_unchanged=true` |

## 实际结果与资格

14 个固定控制全部符合预期：2 个正确控制通过、11 个错误控制被拒绝、1 个失败传播哨兵失败。每个控制保留 69 个观测检查与 138 个标量实际值；`false_acceptances=[]`，`qualified_for_generated_control_discrimination=true`。其中 `reset_ignored` 返回码为 1，实际有 18 个不匹配，已被此次研究测试检出。

这里使用的是新生成的研究测试台，`generated_research_test=true`、`original_harness=false`。此结果仅证明该研究测试对这组有限固定控制具有区分能力，不能称为原 harness 合格、自然题正确率或独立模型分数；也不能修复或取消 FIFO62 原 harness 的漏检排除结论。`independent_quality_admitted=0`、`eligible_for_independent_models=false`、`adoption=false`。本轮没有策略采用或发布。

固定实际收据保留在 `raw_evidence/TERMINAL_DOWNLOAD_RECEIPT.json`、`raw_evidence/TERMINAL_AUDIT_RECEIPT.json`；实际审计结果保留在 `raw_evidence/terminal_audit_v1/RESULTS.json`。本文件只公开元数据，不公开题面原文、RTL 或测试台。
