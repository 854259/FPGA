# ROSS 其他专家技能与知识库：用途评估及仿真实测

有实际价值，当前优先级最高的是 RTL 仿真工作流。2026-10-04 在 AMD 云端通过官方 MCP 和 Vivado 2026.1 完成了一个自建小契约的正负控制：正确加法通过全部5次检查，XOR错误稿在1ns的 `1+1` 检查失败。两者的启动与运行Tcl返回码均为0；完整日志、失败标记及明确完成5检查的PASS标记才能区分结果。这说明官方流程中的判定要求值得使用，不能只看命令成功。

这是人工适配官方技能的工具流程测试，不是本地模型自主执行完整技能，也没有测修复收益。我们的既有研究工具已使用明确判定门槛，本轮不能称为相对现有流程的新检出率或比赛提分。

## 已验证的范围

- 冻结器件 `xczu3eg-sbva484-1-e`，8位组合加法模256，五对合法输入，15ns测试台看门狗，MCP运行上限20ns。输入、研究脚本和预期结果在执行前冻结于 `RUN_SPEC.json`。
- 2个先后独立Vivado会话、22次实际MCP工具调用，37.27秒阶段时间；外层资源守卫37.50秒。正确稿PASS5，错误稿FAIL；全部会话正常关闭，MCP进程正常退出。
- 小测试台和候选均自行构造；0模型调用，不包含官方或隐藏测试台／参考解，不用第三方EDA，不修代码。VCD文件生成并核对文件哈希和表头，未做完整波形数值比对。
- 守卫固定使用 `bde08582` 的资源检查源码，模型与保护文件未变，仅清理本轮后代，残留0、自有锁已释放。10:46:04北京时间只读收尾：模型健康空闲，8000监听，7860/7867不监听，云实例继续运行。
- 私有证据包84文件SHA核验一致，官方8份文档快照SHA核验一致；源文件、执行日志、RPC请求响应、仿真日志、VCD及守卫记录保留，原始包不入Git。结果见 `RESULTS.json`。
- 审计发现 `close_sim` 在运行阶段记录哈希后追加一行内存／CPU统计。原始运行摘要保持；已核对正确／错误稿分别165／281字节的完整判定前缀与原SHA一致，并单列最终日志SHA，追加部分不含新判定。没有以事后哈希覆盖执行时的记录。

## 哪些值得用

| 内容 | 对当前RTL比赛的作用 | 验证状态及决定 |
|---|---|---|
| RTL仿真技能 | 从题面建立明确检查，限定运行，读取完整日志，区分候选错误、测试台错误和环境故障，聚焦首个失配 | 小契约的工具流程与通过／失败门槛已实测；优先纳入后续修复实验设计；模型修复对照未做 |
| 官方知识库 | 查AMD工具命令、错误说明、版本限制和用户指南，减少编造参数 | 官方结构与用途已核验；未部署、未查询、未测检索准确率、延迟或资源。先选择与实际报错相关的官方文档 |
| 时序方法检查技能 | 查时钟／XDC约束及Vivado设计方法问题 | 已读官方技能，未运行；硬件时序方法检查不等同题面中的周期／状态机功能正确性，当前排后 |
| IP、HLS、硬件调试、Vitis AI等 | 在相应工具与硬件任务中有用途 | 当前RTL生成与功能修复任务关联较弱，未实测，不为覆盖工具而扩大系统 |

官方KB的 `amd-doc-search` 是单独MCP，并非现有Vivado MCP已连接就拥有文档检索。官方离线方案包含Weaviate、llama.cpp嵌入服务和MCP三个容器；两种文档包约3.1／4.4GB，嵌入默认可用CPU。本轮没有安装数据库或新模型，不把官方支持离线等同我们的比赛镜像已经兼容。完整KB是否值得接入，需要在具体报错上对比诊断准确率和端到端成本，符合项目最简原则。

比赛开发阶段可参考这些公开工具流程和文档。最终使用的输入、离线资源、镜像和工具权限仍须按冻结比赛规则核验；题面派生的自建测试不得混入隐藏参考或官方测试台。二进制再分发与完整断网容器验收仍未完成。

## 来源与复核

官方来源固定在 `2cdc9eef1b6b5b17fa45f5e4d468e5483a1c92de`，8文件路径和SHA见 `SOURCES.json`：

- [RTL仿真技能](https://github.com/Xilinx/ross-ai-assistant/blob/2cdc9eef1b6b5b17fa45f5e4d468e5483a1c92de/skills/vivado-simulate-rtl/SKILL.md)及同目录xsim、diagnostics、headless-waveform参考。
- [本地知识库](https://github.com/Xilinx/ross-ai-assistant/blob/2cdc9eef1b6b5b17fa45f5e4d468e5483a1c92de/docs/local-kb/README.md)、[FAQ](https://github.com/Xilinx/ross-ai-assistant/blob/2cdc9eef1b6b5b17fa45f5e4d468e5483a1c92de/docs/faq.md)、[工具参考](https://github.com/Xilinx/ross-ai-assistant/blob/2cdc9eef1b6b5b17fa45f5e4d468e5483a1c92de/docs/reference/vivado-mcp-tools.md)。
- [时序方法检查技能](https://github.com/Xilinx/ross-ai-assistant/blob/2cdc9eef1b6b5b17fa45f5e4d468e5483a1c92de/skills/vivado-timing-methodology-checks/SKILL.md)。

云端原始根目录 `/workspace/team/runs/fpga_owner/ross_expert_check_20261004_v1`。持有忽略目录 `raw_evidence/`、`evidence.zip` 及上级ROSS目录 `expert_sources/` 时，在仓库根运行 `python 03_analysis/ross_expert_check_20261004/summarize.py` 复核并重建公开结果；该脚本不会连接云端或调用模型／Vivado。只有原始工具阶段需要通过既有协作slot与冻结资源守卫，不能直接裸跑研究脚本。

下一步应在冻结的真实功能错误和正确稿守卫上，比较“题面检查＋真实诊断修复”与现有重试，记录净修复、回归和时间；本轮2稿不计为2道比赛题。不启用此前未校准的自动lint修复，也不将本轮研究接入正式包。
