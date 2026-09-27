# 2026-09-27 服务器全量结果交接

本轮结果已经完成并从服务器下载核对，运行 ID 为 `full156_20260927_131610_dc69ee`。

- [详细复盘与优化优先级](../../03_analysis/10_AutoDL全量结果与优化建议_20260927.md)
- [公开逐题证据](../../04_project/amd_rtl_agent/bench/results/autodl_full156_20260927.json)：312 份判定、369 次模型调用的允许字段、修复检查状态、原始文件哈希。
- [备份清单](backup-manifest.json)：本地文本证据包与运行源码快照 SHA-256。
- [运行源码快照](runtime-source.tar.gz)：服务器 submission、评测器、测试、工具和启动脚本的下载快照，仅供复现取证，未替换仓库当前运行代码。包含官方 baseline 许可；下载的提交源码与 experiment.json 哈希逐项一致。

本地原始文本证据包位于 `E:/26qiansai/AutoDL-20260927/results-backup-20260927/evidence.tar.gz`，包含本轮全量及参考自检的结果、候选源码、trace 和文本判定日志，不含模型权重、密钥、环境密码或 EDA 二进制缓存。原始文本证据仅在本机保存，GitHub 发布结构化审计结果与运行源码快照。

服务器运行代码包含部署期调整，因此不能只靠准备包的 source-lock 提交号复现。下载的 `submission/runtime.py` 相对原提交增加了 Vivado 版本匹配忽略大小写；其他部署/评测脚本以快照为准。快照中的 model-lock 状态字段来自部署前，不应把其中的 weights_downloaded=false 当作最新进度。模型仓库/revision 是锁定信息，实际部署完成以本次运行证据为准。

复算方式（在项目根目录）：

```text
python tools/summarize_autodl_run.py <文本证据包解压目录> <新的报告路径.json>
```

复算工具只读取结果和日志，不启动模型或 Vivado，不进行收费计算。它检查 complete、156 个唯一题目、无 tool_error 和下载源码哈希，并重新生成逐题及汇总数据。

本轮单样本；原始 156 题口径保留 4 道参考自检非 L3 项。下次试验需要新目录和固定配置，不覆盖本次证据。
