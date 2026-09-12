# AMD RTL 本地智能体（最简实现）

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
