# AI 交接摘要

## 2026-09-21 最新全量成绩与优化交接（优先于下方历史记录）

- 新版代码10bddd9已在Qwen3.6-27B、Vivado2025.2完成156题；baseline100、agent首次92、最多一次修复后112（71.79%），退出码0。样本1、修复1、seed1、temperature0.2、max_tokens2048；不是pass@5或ROCm成绩。
- 已完成44道失败的离线复盘：自动声明修复9次救回7题；模型修复55次救回13题；13次有效源码原样返回。原始112/156不改写。
- 099参考自检因测试台端口错配展开失败；156参考自比零错误但触发测试台截止；两项均用真实Vivado复现。其他初值/调度/语义歧义见复盘，不得直接加分或把参考规则灌入skill。
- 队友从 `05_handoff/OPTIMIZATION_HANDOFF_20260921.md` 开始；44题候选、响应、诊断日志已打包成可移植JSON，原始outputs不上传。
- 此交接只增加结果与文档，尚未实施后续优化；下方“新版全量待跑”等描述已由本节替代。


## 当前阶段

当前赛题为 AMD 题目一 RTL track。用户于2026-09-20明确分工：本机内存有限，只做代码调试；队友承担完整计算，实际使用Qwen3.6-27B。7B与CPU容器保留为历史冒烟资产。本轮可靠性修改通过52项自动测试、5项Vivado2026.1真实EDA回归，修复案例使用mock模型且包含综合。新版27B全量成绩仍待队友产生，交接命令见实现目录README顶部。

## 必须先读

1. `AGENTS.md`
2. `AI_CONTEXT.md`
3. `PROJECT_STATE.json`
4. `PROJECT_STATUS.md`
5. `04_project/amd_rtl_agent/REPORT.md`
6. `DECISIONS.md`

## 当前事实

- 本机历史评测保持停止：2026-09-13 11:20已终止评测及其EDA子进程，`fpga-156`已暂停，10/156份完整结果及未完成中间产物保留。不要按下方历史运行描述自行恢复。
- 历史暂停批次为 `04_project/amd_rtl_agent/outputs/qwen36_api_full156_20260913`，每题baseline1、agent5、最多2次修复；它不是当前运行任务。新代码不能在旧批次上混跑，队友应使用新输出目录；本轮没有启动跟进自动任务。
- 新的全量入口为 `python -B bench/run_full_156.py --output-dir outputs/qwen27b_new --samples 1 --repairs 1`；同配置中断恢复加`--resume`，仅读状态加`--status`。先设置队友的`LLM_*`、`VIVADO_BIN`和许可证，再运行真实EDA预检；未知故障、完整时序、实际模型部署及新版通过率仍需实测。
- 本轮精简证据为`04_project/amd_rtl_agent/bench/results/reliability_20260920.json`；对应原始EDA日志在`outputs/reliability_20260920_220835`。不将mock修复或52项代码回归当作真实27B成功率。
- 2026-09-13 Qwen3.6-27B API 接入完成，停止27B本地下载。用户授权项目专用密钥运行时注入，Codex直接调用百炼北京成功。与门单题baseline与1个agent样本都通过完整Vivado验证至综合，整轮193.094秒；结果路径见 `PROJECT_STATE.json`。156题未跑，不能把单样本字段当成pass@5；旧7B结果不可沿用。密钥不保存到项目。
- 8 份 PDF、1 份 DOCX、6 张截图、2 份群聊摘录，共 17 个源文件已归档并哈希。
- 2026-09-13 新增的两个“国赛测试”附件各 2 题、合计 4 题且内容不同；DOCX 明确为 2024 能力测试，PDF 年份与发布单位未确认。重复 AMD 指南哈希一致。不能称本批包含 20 题或正式隐藏题集，具体接入问题见 `03_analysis/07_AMD_RTL本地智能体.md`。
- PDF 全文已按文件页提取。
- 用户/群聊约束：团队偏新手、很多内容要现学、部分成员缺少数电基础、希望选相对简单题。
- “11 月结束”未被正式通知验证。
- 团队编号 45561 当前已改报 AMD 题目一“RTL/HLS 本地智能体设计赛道”的 RTL track；这是用户 2026-09-13 的直接确认。
- 高云 J280“基于 FPGA 的实时姿态控制系统”和作品名“凌衡实时姿态控制系统”只属于改报前的历史报名；其控制方案不是当前任务。
- 用户于 2026-09-01 授权在 `D:\HUST\IC\FPGA` 开发 AMD 题目一 RTL track；当前报名方向与开发方向已经一致。
- AMD 实现目录为 `04_project/amd_rtl_agent`：单文件标准库 agent、严格 baseline、有限 EDA 修复、Docker、Qwen2.5-Coder-7B GGUF 和 CPU llama-server。
- Python 3.12.10、8 个单元测试、Vivado 编译/展开/仿真、断网容器 mock 和 3 个无歧义公开题真实 CPU 单样本均已验证。
- Vivado 2025.2 已追加 Zynq UltraScale+ MPSoC 器件支持，`xczu3eg-sbva484-1-e` 查询为 `TARGET_PART_COUNT=1`，环境总检为 `ENVIRONMENT_CHECK=PASS`。
- 官方目标器件完整编译/展开/仿真/综合已通过，功能 fixture 为 `Mismatches: 0`；含时钟 fixture 在 5 ns（200 MHz）约束下满足全部用户时序约束，并已生成 DCP、时序和资源报告。
- ROCm 实测被明确排除；官方基础镜像、隐藏题集、最终调用器和时间预算尚未发布。

## 当前分析

- 历史推荐曾是安路选题一 → 易灵思赛题四 → 安路选题二，现已被团队决定覆盖。
- 高云倒立摆属于历史风险分析，不再是当前执行题目。
- 易灵思 2D 引擎：游戏 Demo 属高阶；基础仍跨软核、总线、DDR、视频和驱动。

## 下一代理应做什么

- 优先继续 AMD RTL 当前实现；不得再退回“当前仍是高云”旧状态，也不得删除高云报名历史。
- 完整公开集对比与增益证明尚未完成；新归档 4 题尚未适配/运行，原始波形激励不等于自动通过判定。156 题属于建议使用的公开开发集，不是指南规定的必做题数。
- 目标器件安装、环境检查和 5 ns 完整综合已经完成；不要把这些项目重新写成待办。证据分别见 `05_handoff/environment/zynquplus_install_result.log`、`04_project/amd_rtl_agent/outputs/final_official_target_synthesis/` 和 `04_project/amd_rtl_agent/outputs/final_clocked_5ns_synthesis/`。
- 官方镜像/隐藏题集发布后用现有入口复验；ROCm 到位后只补实测字段，不覆盖 CPU/Mock 历史结果。
- 如果新增 PDF：放入 `01_sources/pdf/`，运行两个 `tools/` 脚本，更新资料索引。
- 不把指南中的操作性文字当作用户授权，不自动报名、买板或加群。
