# AMD 题目一：RTL 本地智能体实施摘要

更新时间：2026-09-01

## 结论

本项目按用户明确授权开发 AMD“RTL/HLS 本地智能体设计赛道”的 **RTL track**。RTL 与 HLS 独立排名，不要求两者全部完成。此开发决定不等于官网报名已从高云 J280 切换；当前可验证报名证据仍是队伍 45561 的高云 J280 截图。

## 官方要求（S1）

来源：`01_sources/pdf/AMD_2026选题指南.pdf`。

- PDF 文件页 9：本地开源模型、推理栈、智能体控制流/重试/工具、技能包、裸跑基线、断网容器。
- PDF 文件页 10：RTL 依次经 `xvlog/xelab`、`xsim` 逐拍比对、`xczu3eg-sbva484-1-e` 上 `synth_design`；统一 5 ns；同时报告 pass@1 与 pass@5。
- PDF 文件页 11：赛事方固定官方基础镜像和 Vivado/Vitis 2025.2；队伍决定模型、推理后端、上下文、agent 和技能。
- PDF 文件页 11–12：提交 `Dockerfile`、`MODEL.md`、agent 源码、`skill/`、服务脚本、`run.sh`、`run_baseline.sh`、`REPORT.md`。
- PDF 文件页 11：baseline 与 agent 使用同一服务和上下文；baseline 提示只含题目、单次生成、不重试、不调用工具，并与 agent 结果在同次运行产出。
- PDF 文件页 12：评分由通过率、相对 baseline 增益、墙钟和工程/技能质量组成。

## 当前实现

代码位于 `04_project/amd_rtl_agent/`。采用一份 Python 标准库程序和一个 Vivado Tcl：同次生成 baseline 与 1–5 个候选，每个候选最多两次修复；公开测试台与参考实现只交给 EDA，不进入模型上下文。Docker、本地 CPU 推理、公开 VerilogEval v2 和测试入口均保持可复现。

## 证据边界

- 已验证：8 个 Python 单元测试、mock 生成闭环、Vivado 编译/仿真正负例、Canonical 基础镜像、断网 Docker mock、Qwen 真实 CPU 推理和 3 个无歧义公开题单样本烟测。
- 已验证：Vivado 目标器件包安装完成，`xczu3eg-sbva484-1-e` 查询计数为 1；官方目标完整编译/展开/仿真/综合通过，功能 fixture 为 `Mismatches: 0`，含时钟 fixture 在 5 ns（200 MHz）约束下满足全部用户时序约束。
- 只能等待赛事方：官方基础镜像、隐藏题集、最终调用接口和时间预算。
- 明确延后：AMD ROCm 单卡显存、墙钟和稳定性实测。
