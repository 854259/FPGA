# AMD RTL 本地智能体（最简实现）

## 当前入口：官方RTL接口适配（2026-09-21）

正式源码在[submission/README.md](submission/README.md)，外部评测入口为
`official_eval.py`，交接见[官方接口交接](../../05_handoff/OFFICIAL_CONTRACT_20260921.md)。
根目录原有run.sh、run_baseline.sh和agent.py继续作为**历史开发有反馈实验入口**，
不用于正式提交。112/156不是官方分级分数。下面的旧流程与历史验证记录保持原样。


## 提示与反馈优化（2026-09-21）

- 编译阶段只新增候选文件绝对路径匹配的单行 VRFC 位宽/截断警告，最多1024字符；与后续失败诊断合计不超过4096字符。其他路径、无来源警告不进入此通道。
- 题面明确要求上电初值时允许 Vivado FPGA 常量初始化；未规定时不补初值。要求只输出精简完整代码，不输出推导注释。
- baseline结果及每轮attempt_history保存response_metadata（返回model、finish_reason、三项token计数）；agent每轮另存response_metadata.json。缺失字段保持缺失；自动声明修复为空对象，不伪造模型响应。length且格式失败时明确提示截断，不额外调用或扩大预算。
- 原始112/156不变。离线核实的099端口错配、156测试台截止见03_analysis/09_新版156题离线复盘_20260921.md；不改数据、不剔题、不向模型注入参考答案。

本机复现：`python -B -m unittest discover -s tests -q`；`python -B tests/run_vivado_regression.py --prompt-feedback-only --output-dir outputs/prompt_feedback_check_new`。
代码/skill已变化，真实模型必须另开实验目录。本机固定响应EDA结果只证明控制流程和工具兼容性，不证明27B收益。

## 后续修复反馈优化（2026-09-20）

- 修复端口方向误报：`input clk, output q`不会再被说成`q`是输入；忽略注释、字符串和其他模块。
  只检查简单ANSI端口；参数化、宏、非ANSI等复杂接口保留原始工具反馈，不猜方向。
- 修复结果退步且仍有修复机会时，下一轮使用验证结果较好的代码及其对应反馈；相同质量继续使用新候选。
  `attempt_history[].repair_from_attempt`记录从哪一轮继续。比较沿用验证阶段和归一化错误率，不能保证其等价于语义上更接近正确解。
- 保留报错紧邻两行内的时间和源位置；反馈仍最多4096字符。初始生成skill、裸模型baseline、模型设置、修复预算不变。
  `--repairs 1`最多修复一次，不会为了回退额外调用模型；回退后再修复需要现有预算还有剩余。

低内存本机复现（固定模型响应，真实Vivado编译/仿真，不做综合）：

```powershell
python -B -m unittest discover -s tests -q
python -B tests/run_vivado_regression.py --repair-backtrack-only --output-dir outputs/repair_feedback_check_new
```

本轮57项自动测试通过；上述真实流程验证“仿真失败→编译失败→从较好候选继续→仿真通过”，
5个断言通过。证据`bench/results/repair_feedback_20260920.json`。这不代表新版27B通过率或综合/时序结论。
队友执行全量时仍沿用下节命令，但必须使用新的输出目录；修改代码后不能恢复旧版本实验。

## 当前分工与本轮修复（2026-09-20）

用户已确认：本机受内存限制，只做代码调试；完整计算交给队友，实际评测使用
Qwen3.6-27B。7B CPU 模型与相关镜像是历史冒烟环境，不是当前正式评测模型。
通用 agent 不强制模型名称，启动脚本默认 27B，已配置的服务、模型和工具路径优先。

本轮主要修改：

- `bench/run_full_156.py` 直接调用统一的 `agent.py benchmark`，必须显式指定输出目录。
  不再寻找最近的历史目录、不再单独拼接 progress.jsonl，也不自动循环重试模型请求。
  只有 `--resume` 且指纹一致时才能恢复；旧格式实验仅保留查阅，另开新实验。
- 已识别的工具缺失、许可证缺失、器件缺失会保存日志并停止评分，不进入 RTL 修复。
  当前题写 `error.json`，没有成绩或检查点；已完成题不丢失，整批保持未完成。
- 单题 `run`、独立 baseline 和重复 EDA 工作目录拒绝覆盖已有证据。
  续跑校验增加 `.log/.rpt/.dcp/PASS`，文件哈希按块读取以降低内存占用。
- 综合通过同时要求正确退出、无 ERROR/FATAL、准确完成标志及非空 PASS、DCP、时序和资源报告。
  `clock_period_ns` 仍是约束配置；新增 `clock_period_is_constraint`、实际 `constrained_clock_ports`
  与 `timing_pass=null`，不把综合通过写成 200MHz 时序已达标。
- 多个样本间沿用样本内的验证阶段/错误比例排序，避免仅因顺序靠前选中更差失败候选。
- EDA 超时或普通中断会尝试终止 Windows 进程树或 POSIX 进程组；保留中断前日志。
  负例回归要求预期 RTL 诊断，修复流程也检查综合，不接受“缺许可证导致失败”作为负例通过。

队友在配置好实际 `LLM_BASE_URL`、`LLM_API_KEY`、`VIVADO_BIN` 和许可证后，从此目录运行：

```powershell
$env:LLM_MODEL = 'qwen3.6-27b'
# 请先按队友机器设置 VIVADO_BIN 和已有模型服务，不照抄本机 F 盘路径。
python -B tests/run_vivado_regression.py --output-dir outputs/preflight_20260920
python -B bench/run_full_156.py --output-dir outputs/qwen27b_20260920_new --samples 1 --repairs 1
# 同一代码、环境和数据下中断恢复：
python -B bench/run_full_156.py --output-dir outputs/qwen27b_20260920_new --samples 1 --repairs 1 --resume
# 仅读进度，无模型调用：
python -B bench/run_full_156.py --output-dir outputs/qwen27b_20260920_new --status
```

先检查 preflight 全部通过再执行全量命令。新的代码/技能/模型预算必须用新目录，不能为继续跑
而修改 `experiment.json` 或检查点。已有旧 10/156 批次保持暂停，不自动迁移或恢复。
`tools/check_environment.ps1` 默认只检查 Python、Vivado 与目标器件；仅显式加
`-IncludeLocalRuntime` 时才检查历史 7B 权重与启动 WSL/Docker。

本轮不会自动下载/加载 27B、启动模型服务或执行收费评测。仍需队友验证新版完整 156 题、pass@5、
实际显存与墙钟、目标部署环境。未知的工具故障文本、同一路径下被替换的工具/服务版本、完整时序
约束与官方最终评分口径仍不能由本轮修改保证；详见项目分析与交接文档。

本机验证：52 项自动测试通过，Vivado 2026.1 的 5 项真实 EDA 回归通过，其中 mock 模型
修复后的候选也经过综合。Windows 超时子进程回收已用真实小进程验证；POSIX 分支未实测。
精简证据：`bench/results/reliability_20260920.json`。这不是新版 27B 成绩。

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
