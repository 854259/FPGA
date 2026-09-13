# 项目状态

更新时间：2026-09-12

## 当前同步内容：2026-09-12

- GitHub 同步分支：`fix/reliable-evaluation`，包含评测可靠性修复、云端启动脚本和 14 项自动测试。
- 当前 Qwen3.6-27B 公开集前 10 题：baseline 10/10，agent 10/10，均首次生成通过 Vivado 编译、仿真和综合。原 20 题实验按用户要求中止。
- 可移植精简报告：`04_project/amd_rtl_agent/bench/results/qwen_cloud_first10_20260912.json`。原始日志、缓存、权重及密钥不上传。
- 下文“尚未推送”“未重跑”等为当日历史记录，以本节和后续 2026-09-12 记录为准。

## 本次优化：2026-09-10

- 在 `E:/26qiansai/FPGA-teammate-review` 的本地分支 `fix/reliable-evaluation` 修改，尚未推送 GitHub。
- 修正超时日志崩溃；修复循环保留验证阶段更好的候选，同时保存每次原始响应、代码与评测记录。
- 结果升级为 schema 2：不足 5 个样本不报告 pass@5；跳过 EDA 或没有测试台时，功能通过率为 `null`，不再冒充通过。
- 仿真要求所有 `Mismatches` 计数为零且无 ERROR/FATAL；批测提前检查数据三元组，每题结束保存进度，并标记整批是否完成。
- 14 项 Python 测试通过（含真实子进程超时测试；模型与 EDA 场景采用模拟返回值）。尚未在本次机器重跑真实模型、Vivado、Docker 或 ROCm，不能宣称通过率或推理速度提升。
- 下一步：在原开发机按实现目录 README 运行 20 题、单样本、一次修复对照实验，使用新的输出目录；之后再做 5 样本实验和 ROCm 复验。

以下为 2026-09-01 原开发机的历史状态，环境、赛事公告及报名事项未在本次重新核验。

## 结论

- 用户已授权在 `D:\HUST\IC\FPGA` 开发 AMD 题目一的 **RTL track**；实现目录为 `04_project/amd_rtl_agent`。
- 现有报名证据仍显示队伍 `45561` 报名高云 J280。尚无 AMD 改报截图，因此“报名事实”和“当前开发目标”分开记录，不能互相冒充。
- 除 AMD ROCm 实测和赛事方尚未公开内容外，当前可在本机执行的环境、代码、模型、容器、Vivado 官方目标器件综合与 5 ns 时序验证均已落地。
- 项目已发布到公开仓库 `https://github.com/854259/FPGA` 的 `main` 分支；首次导入提交为 `ad143eb`，提交邮箱为 `3260548169@qq.com`。
- 已向 GitHub 用户 `nzh152-lang` 发出 Write 协作者邀请；GitHub 已创建邀请，当前等待对方接受，尚不能写成已加入完成。

## 已完成并验证

- 归档 7 份厂商指南 PDF、4 张关键截图和 2 份群聊摘录，共 15 个原始来源文件；已生成逐页文本、元数据、链接和 SHA-256 清单。
- 安装并验证 Python 3.12.10。
- 验证 Vivado/Vitis 2025.2 的 `xvlog`、`xelab`、`xsim` 和批处理 Tcl 入口；已追加 Zynq UltraScale+ MPSoC 器件支持，`xczu3eg-sbva484-1-e` 查询计数为 1，环境总检为 `ENVIRONMENT_CHECK=PASS`。
- 在 WSL2 安装 Docker Engine 29.7.2；从 Canonical 校验后导入 Ubuntu 22.04 OCI rootfs。最终镜像包含模型和 CPU llama.cpp runtime，并在 `--network none` 下通过真实模型健康检查、最短生成请求及 mock agent 闭环。
- 下载并校验 Qwen2.5-Coder-7B-Instruct Q4_K_M，大小 `4,683,073,536` 字节，SHA-256 `509287f78cb4d4cf6b3843734733b914b2c158e43e22a7f4bf5e963800894d3c`。
- 编译 CPU `llama.cpp` 服务，固定 commit `010be9683afabe14ce299197b38c329f94bae568`。
- 最终镜像 ID 为 `sha256:a449bd5e2200162d42a34f57160fcaf56fe7dd857cc8de331f2ca37add80841f`，大小 `4,645,865,911` 字节；断网真实模型请求返回 `OK.`。
- 实现严格单次 baseline、RTL 技能、1–5 个独立样本、最多 2 次修复、Vivado 编译/展开/逐拍仿真/综合、结构化结果和 Docker 入口。
- 参考答案和测试台只用于 EDA，不进入模型上下文；修复只接收精简后的工具日志。
- 8 个 Python 单元测试全部通过；mock baseline + 5 样本通过；Vivado 正例和编译/功能负例均按预期分类。
- 在官方指定器件 `xczu3eg-sbva484-1-e` 上完成完整编译、展开、仿真与综合：功能 fixture 为 `Mismatches: 0`，并生成 `post_synth.dcp`、时序报告和资源报告。
- 额外使用含真实时钟端口的 fixture 进行 5 ns（200 MHz）综合；时序报告明确为 `All user specified timing constraints are met.`。
- 接入 NVlabs VerilogEval commit `c498220d0a52248f8e3fdffe279075215bde2da6`，共 156 组三元组；真实 7B CPU 小样本验证已运行，详见 `04_project/amd_rtl_agent/REPORT.md`。
- Git 上传前已排除 4.68 GB 模型权重、生成缓存、认证日志、群聊原文、报名截图和其他队伍截图；这些本机文件均保留未删除。仓库包含源码、测试、脚本、说明文档、公开指南和精简后的综合/时序验证报告。

## 当前未完成及原因

1. **AMD ROCm 实测**：按用户要求排除；显存、墙钟时间和最终稳定性不得估算。
2. **赛事方外部依赖**：官方基础镜像、隐藏题集、最终调用器和时间预算尚未发布，当前只能保留兼容入口，不能伪造最终验收。
3. **AMD 报名状态**：开发已获授权，但尚无队伍 `45561` 改报 AMD 的证据。

## 剩余外部输入

- 等赛事方发布官方基础镜像、隐藏题集、最终调用器和时间预算后，用现有入口复验。
- 若团队确实改报 AMD，补存队伍 `45561` 的官网变更证据。
- ROCm 硬件可用且用户要求补测时，再记录显存、墙钟和稳定性；不得用 CPU 数据估算。

## 2026-09-12 当前机器验证
- 在 E:/26qiansai/FPGA-teammate-review 执行；历史 D 盘目录在本机不存在。
- E:/vivado/2025.2/Vivado/bin：固定 AND 样例编译、展开、仿真、综合通过，Mismatches: 0。证据：04_project/amd_rtl_agent/outputs/local_preflight_20260912。
- 14 项单元测试通过。新增可选 LLM_ENABLE_THINKING 参数及 run_cloud_smoke.ps1；云端 Qwen3.6-27B 真实闭环仍待用户在已配置临时密钥的 PowerShell 中启动，不能称为云端验证通过。

## 2026-09-12 本轮复测
- Python 3.11.9 下运行全部 14 项单元测试，全部通过（1.617 秒）。
- 固定 correct.sv 样例在当前 E 盘 Vivado 2025.2 下完成编译、展开、仿真、综合，各步骤退出码为 0；Mismatches: 0。
- 测试日志：04_project/amd_rtl_agent/outputs/retest_20260912/correct。
- 当前进程未配置 LLM_API_KEY，未执行云端真实模型测试；以上结果不代表模型生成通过率。

## 2026-09-12 API 接入入口
- run_cloud_smoke.ps1 支持读取当前进程/用户级 LLM_API_KEY，缺失时在终端隐藏输入；密钥不写入项目文件。
- 保留现有 Qwen 服务地址、qwen3.6-27b 模型和真实模型 + Vivado 测试入口；Python 改为使用当前环境命令。
- PowerShell 语法检查通过。当前机器未配置密钥，尚未验证 API 连通性或真实生成结果。

## 2026-09-12 云端真实模型测试通过
- 用户在终端输入密钥并启动 run_cloud_smoke.ps1，qwen3.6-27b API 已验证连通。
- outputs/cloud_smoke_20260912_225041/result.json：mock_model=false，baseline_pass=true，单个 agent 样本首次生成通过编译、仿真和综合，无需修复；进程退出码 0，总耗时 118.891 秒。
- 证据目录位于 04_project/amd_rtl_agent/outputs/cloud_smoke_20260912_225041。
- 本次仅为 AND 门题目的真实模型冒烟测试，不代表公开题集通过率；pass_at_5=null，真实模型修复分支未触发。此前待密钥/待云端验证记录为历史状态。

## 2026-09-12 公开数据集就绪
- 已获取 NVlabs/verilog-eval 并固定到 c498220d0a52248f8e3fdffe279075215bde2da6。
- dataset_spec-to-rtl 的 156 组题面、参考和测试台完整。
- benchmark --limit 20 按排序选择 Prob001_zero 至 Prob020_mt2015_eq2；本轮仅核对数据，尚未运行 20 题模型评测。

## 2026-09-12 20 题评测入口
- run_cloud_smoke.ps1 新增 -Benchmark20：前 20 题，每题 baseline + 1 个 agent 样本，最多 1 次修复，完整 Vivado 编译/仿真/综合。
- 语法及 20 组三元组完整性检查通过；输出独立 cloud_benchmark20 时间戳目录并汇总通过数量。
- 当前进程及用户环境无 API 密钥，需要用户在终端隐藏输入后启动；20 题评测尚未开始。

## 2026-09-12 云端公开集前 10 题结果
- 按用户最新要求停止于前 10 道完成题；已终止正在运行的第 11 题及其子进程，未计入统计。
- Qwen3.6-27B，VerilogEval v2 固定版本前 10 题：baseline 10/10，agent 10/10；每题 1 个 agent 样本，均首次通过，无修复。
- 两种生成均完成 Vivado 编译、仿真和综合；mock_model=false。10 题耗时合计 1125.189 秒（约 18.75 分钟），不含中断题。
- 原始 benchmark.json 保持 complete=false、requested_problems=20；另存 summary_first10.json 记录用户缩减范围后的结果，不把原 20 题任务标成完成。
- 证据：04_project/amd_rtl_agent/outputs/cloud_benchmark20_20260912_225725/summary_first10.json。
- 此结果仅适用于前 10 题，不能外推完整 156 题通过率；两种方式均满分，尚未体现技能提示或修复的增益。

## 2026-09-13 优化与完整本地回归

- 延续当前 E 盘项目和昨天已接通的云端 API；保留 Qwen3.6-27B 前 10 题 baseline/agent 均 10/10 的历史成绩。本轮未调用云端 API。
- 修正批量统计：schema_version=3，improved_problems 表示相对 baseline 改善；repaired_problems 只统计首个 agent 样本初次失败后实际修复成功的题目。单题格式仍为 2。
- API 空内容、异常响应结构统一明确报错，不额外重试；批量题数拒绝零和负数。
- Python 自动回归 18/18 通过；真实 Vivado 回归 5/5 符合预期：正确代码通过综合，编译/仿真/综合负例分别在预期阶段失败，固定模型响应驱动的修复流程由仿真失败恢复通过。
- 首轮发现旧 synth_fail.sv 实际可综合，已更换为仿真语法合法但时钟不明确的负例，并完整复测。首轮失败记录保留，不覆盖。
- 修复流程使用固定响应和真实 Vivado，不表示真实云端模型修复能力已验证；ROCm 本轮未测。
- 可复现入口：04_project/amd_rtl_agent/tests/run_vivado_regression.py；指定 VIVADO_BIN 和新的 --output-dir。
- 精简报告：04_project/amd_rtl_agent/bench/results/local_regression_20260913.json；完整日志：04_project/amd_rtl_agent/outputs/regression_20260913_verified。

## 2026-09-13 第 11–20 题云端评测准备

- 用户明确要求测试后 10 题；增加 --offset 与 -BenchmarkNext10，严格选择固定公开集第 11–20 题，保留原完整 20 题运行中的 seed 编号。
- 20 项自动测试通过，PowerShell 语法检查通过；固定数据集版本仍为 c498220d0a52248f8e3fdffe279075215bde2da6。
- 当前进程/用户环境均无密钥，准备交互终端隐藏输入后启动。尚未产生新的云端成绩。

## 2026-09-13 第 11–20 题云端验证完成

- Qwen3.6-27B，固定 VerilogEval v2 第 11–20 题：baseline 10/10、agent 10/10；每题 1 个 agent 样本，均首次通过，无修复。真实 Vivado 编译、展开、仿真、综合各阶段退出码均为 0。
- 本轮 complete=true，进程退出码 0，题目耗时合计 1099.498 秒（约 18.32 分钟）。完整证据：04_project/amd_rtl_agent/outputs/cloud_benchmark11_20_20260913_091816。
- 模型参数、技能提示哈希、完整验证模式与昨日一致。两轮独立汇总后前 20 题 baseline 和 agent 均 20/20；本地共有 156 组完整题目，剩余 136 题未评测，不能外推全量通过率或宣称修复增益。
- 精简报告：04_project/amd_rtl_agent/bench/results/qwen_cloud_next10_20260913.json；合并报告：04_project/amd_rtl_agent/bench/results/qwen_cloud_first20_combined_20260913.json。
- 昨日中断的原始 20 题报告保持 complete=false，不覆盖历史记录。此前待密钥记录已由本条完成状态取代。

## 2026-09-13 全量 156 题复盘与 skill 优化完成

- 原始 156 题全部完成：baseline 101/156，agent 首次 94/156，最多一次修复后 110/156；修复成功 16 题，相对 baseline 改善 17、退化 8。此前“剩余 136 题未测”为历史状态。
- 最终失败：格式 4、编译 6、展开 1、仿真 35；62 次修复中 15 次代码未变。复盘脚本与证据：04_project/amd_rtl_agent/bench/analyze_run.py、bench/results/full156_failure_analysis_20260913.json。
- 提炼并接入生成 skill 与仅修复时加载的 RTL_REPAIR_SKILL.md：变量声明、作用域、精简完整代码、时序、状态机和基于反馈的修复；不含参考答案。两份技能分别记录哈希。
- 修复日志保留首个错误和最终统计；相同阶段优先保留仿真错误比例更低的候选。24 项自动测试通过。
- Qwen3.6-27B 定向复测 5 题（同模型参数和原 seed，1 个样本、最多 1 次修复）：旧版 1/5，新版 3/5。Prob030 首次通过、Prob054 修复通过、Prob001 保持通过，均完成真实 Vivado 仿真和综合；Prob039 与 Prob108 仍编译失败。
- 定向成绩证据：04_project/amd_rtl_agent/bench/results/optimization_subset_20260913.json；详细复盘：03_analysis/08_全量156题优化与技能总结.md。
- 该样本按失败类型选择，只能说明局部结果；新版 156 题全量成绩未测，不外推通过率。本次变更未发布。

## 2026-09-13 编译驱动修复与重复检测验证完成

- agent 根据 Vivado VRFC 10-1280 报错，将简单 ANSI 输出声明中的对应 output/output wire 修正为 output reg，保留位宽、符号、方向与逻辑；宏、参数化及复杂声明不自动修改。修正占已有修复次数，仍需完整 EDA 验证。
- 同一样本内按精确代码哈希检测重复，重复的格式/编译失败复用已完成诊断，下一次模型提示明确指出原样返回。超时、工具缺失和仿真不缓存。记录 source、duplicate_of_attempt、evaluation_reused、model_calls。
- 30 项自动测试通过。两道历史失败代码 Prob039、Prob058 重放均由编译失败经一次声明修正通过真实 Vivado 仿真和综合（分别 Mismatches: 0 in 114 / 219 samples）。
- 本轮使用归档候选替代模型响应，没有调用云端 API；这是修复控制逻辑验证，不是新的模型成绩，不能合并进旧 156 题通过率。模型配置未切换。
- 复现入口：04_project/amd_rtl_agent/tests/run_declaration_regression.py；精简证据：04_project/amd_rtl_agent/bench/results/declaration_regression_20260913.json。未发布。

## 2026-09-13 批量实验续跑与统计

- 新增 benchmark --resume，按完成题检查点恢复，核对模型配置、代码/skill、题目/测试台/参考内容哈希和结果文件。未完成题在 restart_N 新目录重跑；保留中断证据。
- 输出目录防覆盖、单写入进程锁；旧实验无配置清单时不冒充可续跑。恢复不依赖可能尚未写完的总报告，而使用逐题原子检查点。
- schema_version 4 新增模型调用数、生成耗时与 EDA 耗时；未完成题历史尝试耗时未计入汇总。旧批量启动器改用独立尝试目录，执行异常题可重新运行。
- 39 项单元测试通过（包括中断、检查点先于总报告保存、配置/数据变化、结果篡改、目录锁、秘密字段不落盘）；真实 CLI 两题 mock 首跑与续跑一致。证据：04_project/amd_rtl_agent/bench/results/resume_regression_20260913.json。
- 用户计划国庆租 RTX 5090 一周测试 Qwen3.8-27B，当前仅计划，尚未租用/部署。GPU 与云端模型本轮未测；AMD ROCm 验证仍需单独完成。
