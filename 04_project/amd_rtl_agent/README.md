# AMD RTL 本地智能体（最简实现）

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
docker build --network host -t amd-rtl-agent:dev .
bash tests/container_smoke.sh
bash tools/download_model.sh
```

公开集：

```powershell
python .\agent.py benchmark `
  --dataset .\bench\verilog-eval\dataset_spec-to-rtl `
  --output-dir .\outputs\verilog-eval `
  --limit 3
```

## 当前不能冒充完成的事项

- AMD ROCm 单卡实测、显存和最终墙钟数据。
- 赛事方尚未公开的官方基础镜像、隐藏题集、最终调用接口与评分时间预算。
- 若 `check_environment.ps1` 报目标器件为 0，须由 AMD 安装器追加 Zynq UltraScale+ MPSoC support 后才能做官方目标综合。

详细证据与复现状态见 `REPORT.md` 和顶层 `PROJECT_STATUS.md`。
