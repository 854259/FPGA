# 项目状态

更新时间：2026-09-01

## 结论

- 用户已授权在 `D:\HUST\IC\FPGA` 开发 AMD 题目一的 **RTL track**；实现目录为 `04_project/amd_rtl_agent`。
- 现有报名证据仍显示队伍 `45561` 报名高云 J280。尚无 AMD 改报截图，因此“报名事实”和“当前开发目标”分开记录，不能互相冒充。
- 除 AMD ROCm 实测和赛事方尚未公开内容外，当前可在本机执行的环境、代码、模型、容器、Vivado 官方目标器件综合与 5 ns 时序验证均已落地。

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

## 当前未完成及原因

1. **AMD ROCm 实测**：按用户要求排除；显存、墙钟时间和最终稳定性不得估算。
2. **赛事方外部依赖**：官方基础镜像、隐藏题集、最终调用器和时间预算尚未发布，当前只能保留兼容入口，不能伪造最终验收。
3. **AMD 报名状态**：开发已获授权，但尚无队伍 `45561` 改报 AMD 的证据。

## 剩余外部输入

- 等赛事方发布官方基础镜像、隐藏题集、最终调用器和时间预算后，用现有入口复验。
- 若团队确实改报 AMD，补存队伍 `45561` 的官网变更证据。
- ROCm 硬件可用且用户要求补测时，再记录显存、墙钟和稳定性；不得用 CPU 数据估算。
