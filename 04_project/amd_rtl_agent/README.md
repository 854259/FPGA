# AMD RTL 本地智能体（最简实现）

## 批量续跑与实验记录（2026-09-13）

批量报告升级为 schema_version 4，单题仍为 2。`benchmark --resume` 会跳过已完成题，
要求相同的题目/参考/测试台内容、模型配置、代码与技能版本；配置不同请使用新目录。
已完成候选或结果被改动时拒绝恢复。只有完整题目设检查点，中断题会保留旧文件并在
`restart_N` 子目录重新生成 baseline 和 agent，不在半次模型生成上续写。

```powershell
python agent.py benchmark --dataset bench/verilog-eval/dataset_spec-to-rtl --output-dir outputs/experiment_new --samples 1 --repairs 1
# 中断后，保持环境参数和其他命令参数一致，加 --resume
python agent.py benchmark --dataset bench/verilog-eval/dataset_spec-to-rtl --output-dir outputs/experiment_new --samples 1 --repairs 1 --resume
```

新实验拒绝覆盖非空目录；历史实验没有 `experiment.json` 与检查点时不能直接续跑。
`.benchmark.lock` 防止同时写入；强制结束进程留下锁时，先确认锁中 PID 对应进程已结束，
再移除该锁文件。不要删除仍在运行的任务的锁。

报告新增模型调用次数、模型生成耗时与 EDA 耗时（含已完成题的历史累计值）；
未完成尝试耗时未纳入该汇总，完整租机墙钟仍需另外记录。
`experiment.json` 记录输入哈希与配置，不保存 API 密钥，服务地址仅保存哈希。
建议用 `LLM_MODEL_REVISION`、`LLM_QUANTIZATION` 声明实际部署版本；这些是记录字段，
不会自动改变远端模型。相同地址背后的服务若被替换，仍需人为冻结部署并另开实验。

39 项自动测试及两题 mock CLI 首跑/续跑检查通过；本轮未产生新的云端或 GPU 成绩。

## 编译反馈驱动修复与重复检测

当 Vivado 明确报 `VRFC 10-1280`（过程赋值目标不是变量），agent 可直接将
简单 ANSI 接口中的对应 `output` / `output wire` 改为 `output reg`。
保留方向、位宽、符号属性和逻辑；复杂声明、宏和参数化接口交回模型处理。
这一修正占用一次已有修复机会，并重新执行 EDA，不增加修复上限。

相同样本内按代码哈希检测重复。完全相同代码的格式/编译失败可复用已完成的诊断，
并在下一次模型提示中说明重复；超时、工具缺失及仿真结果不作缓存。
每轮新增 `source`、`duplicate_of_attempt`、`evaluation_reused`；样本新增 `model_calls`。
`compiler_declaration_repair` 表示代码规则修复，不应统计成模型独立修复能力。

无云端请求的历史代码重放验证入口（需配置 `VIVADO_BIN`）：

```powershell
python tests/run_declaration_regression.py --source-run outputs/full156_20260913_111459 --output-dir outputs/declaration_replay_new
```

## 2026-09-13 全量复盘与技能优化

原始完整 156 题：baseline 101/156，agent 首次生成 94/156，最多一次修复后
110/156；实际修复成功 16 题，相对 baseline 改善 17 题、退化 8 题。
下方“剩余 136 题未评测”为历史进度，已被本次完整结果取代。

- `skill/RTL_SKILL.md`：生成时加载的声明、紧凑代码、逐拍时序、状态机与计数规则。
- `skill/RTL_REPAIR_SKILL.md`：失败后才加载的诊断与修复规则，单独记录哈希。
- 修复日志保留首个报错和最终统计；同阶段失败候选优先保留仿真错误比例较低者。
- 24 项自动测试通过。真实模型定向复测结果见
  `outputs/optimization_subset_20260913/summary.json`；这不是新版完整集成绩。

离线复盘（不调用模型）：

```powershell
python bench/analyze_run.py --source-run outputs/full156_20260913_111459 --output outputs/full156_analysis.json
```

沿用原实验的 `LLM_*` 和 `VIVADO_BIN` 环境，可在新目录定向复测；
程序核对模型参数及题目哈希，沿用原样本 seed，每题最多一次修复：

```powershell
python bench/retest_subset.py --source-run outputs/full156_20260913_111459 --output-dir outputs/subset_new --problems Prob030_popcount255 Prob039_always_if
```

此入口只重跑 agent，不生成新 baseline，不能用作正式同轮 baseline 对比。
完整复盘与技能来源见 [`../../03_analysis/08_全量156题优化与技能总结.md`](../../03_analysis/08_全量156题优化与技能总结.md)。

## 2026-09-13 回归与统计更新

批量汇总使用 `schema_version: 3`（单题结果仍为 2）：`improved_problems`
表示 baseline 失败而首个 agent 样本最终通过；`repaired_problems` 只统计首个
agent 样本初次失败、实际修复后通过的题目，与 baseline 是否通过无关。
未执行功能验证或尚未完成任何题目时，修复数量为 `null`。历史报告不改写。

API 空内容或异常响应结构会明确报错且不自动重试；`--limit` 必须为正数。
无需云端密钥的真实 Vivado 回归入口（输出目录须为空或不存在）：

```powershell
$env:VIVADO_BIN = 'E:\vivado\2025.2\Vivado\bin'
python tests/run_vivado_regression.py --output-dir outputs/vivado_regression
```

覆盖正确、编译失败、仿真失败、综合失败四种 RTL，以及使用固定响应驱动的
真实仿真修复流程。该修复测试使用假模型，不代表云端模型的修复能力。

## 2026-09-12 云端验证

Qwen3.6-27B 在 VerilogEval v2 固定版本前 10 题上，baseline 与 agent 均为 10/10，
全部首次通过 Vivado 编译、仿真和综合，无需修复。每题仅 1 个 agent 样本；
原 20 题实验按用户要求提前停止，不能外推完整集通过率或技能增益。
精简报告见 [`bench/results/qwen_cloud_first10_20260912.json`](bench/results/qwen_cloud_first10_20260912.json)。

Windows 云端入口为 `run_cloud_smoke.ps1`，启动时隐藏输入 API 密钥；加 `-Benchmark20`
运行固定数据集前 20 题。需先按 `bench/VERILOG_EVAL.md` 获取数据集，并按本机配置
检查脚本中的服务地址、模型和 Vivado 路径。密钥不写入项目文件。

本目录只实现 AMD 题目一的 **RTL track**；不实现 HLS。核心是一份标准库 Python 程序，不使用 LangChain、RAG、数据库、多智能体或中间抽象层。

## 已实现

- 严格裸跑基线：题目原文作为唯一 user message、一次生成、不重试、不调用工具。
- agent：同一模型配置，加载短 RTL 技能，5 个独立 seed，每个最多 2 次修复。
- Vivado 2025.2：`xvlog → xelab → xsim → synth_design`；目标 `xczu3eg-sbva484-1-e` 已安装并完成正式综合，含时钟 fixture 在 5 ns（200 MHz）约束下满足全部时序约束。
- 公共 VerilogEval v2 三元组接入和 pass@1/pass@5 汇总。
- Canonical Jammy 本地基础镜像、Dockerfile、断网 mock 冒烟。
- 镜像内置已校验的 Qwen 7B 权重和 CPU llama.cpp runtime；断网真实模型健康检查与最短生成请求已通过。
- OpenAI-compatible 本地推理接口；CPU 与后续 ROCm 只需替换服务实现。

## 入口

Linux/官方容器入口：

```bash
./run_baseline.sh problem.txt output.sv
./run.sh problem.txt output_dir [test.sv] [ref.sv]
```

Windows 本地开发：

```powershell
$env:VIVADO_BIN = 'F:\vivado\2025.2\Vivado\bin'
python .\agent.py run --problem .\tests\fixtures\problem.txt `
  --output-dir .\outputs\smoke `
  --testbench .\tests\fixtures\test.sv `
  --reference .\tests\fixtures\ref.sv
```

`run` 会在同一次实验中先生成并评测 `baseline.sv`，再生成 agent 样本。参考实现和测试台只传给 EDA，不传给模型。

## 环境与验证

```powershell
.\tools\check_environment.ps1
python -m unittest discover -s .\tests -v
```

```bash
bash tools/bootstrap_base_image.sh
bash tools/download_model.sh
docker build --network host -t amd-rtl-agent:dev .
bash tests/container_smoke.sh
```

公开集：

```powershell
python .\agent.py benchmark `
  --dataset .\bench\verilog-eval\dataset_spec-to-rtl `
  --output-dir .\outputs\verilog-eval `
  --limit 20 --samples 1 --repairs 1 --skip-synthesis
```

## 当前不能冒充完成的事项

### 2026-09-10 评测可靠性更新

结果格式更新为 `schema_version: 2`。`passed` 表示所执行检查是否通过；
`baseline_pass`、`pass_at_1`、`pass_at_5` 才是功能评测字段。
未提供测试台或使用 `--skip-eda` 时，功能指标为 `null`；少于5个样本时
`pass_at_5` 为 `null`，不能当成0或100%。`--skip-synthesis` 结果仅表示仿真级别。
`mock_model` 标记假模型实验，不能报告为真实模型成绩。

每轮修复保存 `response.txt`、`candidate.sv`、`evaluation.json`；最终保留验证阶段最高的
尝试，避免后续修复退化覆盖较好代码。`selected_attempt` 指向被选中的轮次。
基线的评测日志也会保存；`skill_sha256` 用于追踪提示规则版本。

批量评测启动前检查题目、参考和测试台是否齐全；每完成一道题，原子更新
`benchmark.json`，记录净修复相关计数、退化题数和平均耗时。
`complete: false` 表示中途失败或未完成，不能当成完整集结果。此版本保留进度，
尚不自动续跑；重复实验请使用新的输出目录。

以上优化已通过自动回归测试；真实模型通过率和ROCm性能仍需后续实测。

- AMD ROCm 单卡实测、显存和最终墙钟数据。
- 赛事方尚未公开的官方基础镜像、隐藏题集、最终调用接口与评分时间预算。
- 若 `check_environment.ps1` 报目标器件为 0，须由 AMD 安装器追加 Zynq UltraScale+ MPSoC support 后才能做官方目标综合。

详细证据与复现状态见 `REPORT.md` 和顶层 `PROJECT_STATUS.md`。

测试公开集第 11–20 题：`./run_cloud_smoke.ps1 -BenchmarkNext10`。独立保存到 `outputs/cloud_benchmark11_20_时间戳`；完整 Vivado 检查，每题 1 个 agent 样本、最多 1 次修复。

## 2026-09-13 第 11–20 题云端验证完成

- Qwen3.6-27B，固定 VerilogEval v2 第 11–20 题：baseline 10/10、agent 10/10；每题 1 个 agent 样本，均首次通过，无修复。真实 Vivado 编译、展开、仿真、综合各阶段退出码均为 0。
- 本轮 complete=true，进程退出码 0，题目耗时合计 1099.498 秒（约 18.32 分钟）。完整证据：04_project/amd_rtl_agent/outputs/cloud_benchmark11_20_20260913_091816。
- 模型参数、技能提示哈希、完整验证模式与昨日一致。两轮独立汇总后前 20 题 baseline 和 agent 均 20/20；本地共有 156 组完整题目，剩余 136 题未评测，不能外推全量通过率或宣称修复增益。
- 精简报告：04_project/amd_rtl_agent/bench/results/qwen_cloud_next10_20260913.json；合并报告：04_project/amd_rtl_agent/bench/results/qwen_cloud_first20_combined_20260913.json。
- 昨日中断的原始 20 题报告保持 complete=false，不覆盖历史记录。此前待密钥记录已由本条完成状态取代。
