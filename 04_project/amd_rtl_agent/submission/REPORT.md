# AMD RTL 本地智能体设计报告

更新时间：2026-09-01

## 1. 目标与边界

仅完成 AMD 题目一的 RTL track。输入是题目文本，输出是单个 `TopModule`。HLS、训练微调和 ROCm 最终性能验证不在当前实现中。官方基础镜像、隐藏题集和最终调用协议未发布，因此以可替换入口隔离，不声称已通过赛事方最终验收。

## 2. 架构

```text
problem.txt
  ├─ baseline：同模型、题目原文、单次生成 ──> baseline.sv
  └─ agent：题目 + RTL_SKILL.md
       └─ 生成 ─> xvlog/xelab ─> xsim ─> synth_design
                    └─ 精简错误反馈，最多修复 2 次
```

实现保持扁平：`agent.py` 直接包含推理请求、代码提取、EDA 子进程、有限修复和 benchmark；没有框架、数据库、检索层或插件系统。参考实现和测试台只进入 EDA 命令，绝不进入模型消息。

## 3. 模型与推理

推理采用 OpenAI-compatible `/v1/chat/completions`，使 CPU `llama.cpp` 与后续 ROCm 服务共用同一个 agent。当前冻结候选为 Qwen2.5-Coder-7B-Instruct GGUF Q4_K_M；revision、字节数和 SHA-256 见 `model/MODEL.md`。baseline 与 agent 共用模型、温度 0.2、8192 上下文和 2048 输出上限。

放弃当前引入更大模型、微调和多模型路由：这些方案会增加显存、构建和复现成本，尚无公开集证据证明收益。

## 4. 控制流与回退

- baseline：恰好一次模型调用；无技能、无重试、无工具调用。
- agent：默认 5 个独立 seed；每个初始生成一次，失败最多修复两次。
- 验证顺序：格式、`xvlog`、`xelab`、可用时 `xsim` 逐拍比较、目标器件综合。
- 反馈：只保留错误、mismatch、timeout 等关键行，最多 4096 字符。
- 超时：每个 EDA 子进程独立超时；超时按失败处理。
- 最佳候选：优先通过者，其次取达到最高验证阶段且尝试次数更少者。

## 5. 技能包

`skill/RTL_SKILL.md` 只保留直接影响可综合性和逐拍一致性的规则：接口严格匹配、完整组合赋值、非阻塞时序赋值、位宽/符号、复位语义和禁止不可综合结构。技能没有引用具体公开题答案。

## 6. 已验证结果

以下为本机可复现工程验证，不是比赛成绩：

- Python 3.12.10；8 个单元测试通过。
- mock 同次运行成功产出 1 个 baseline、5 个 agent 候选、`best.sv` 和 `result.json`。
- Vivado 2025.2 正例：`xvlog`、`xelab`、`xsim` 通过，日志包含 `Mismatches: 0`。
- Vivado 2025.2 已安装目标器件支持，`xczu3eg-sbva484-1-e` 查询计数为 1；`tools/check_environment.ps1` 返回 `ENVIRONMENT_CHECK=PASS`。
- 在该官方指定器件上完成完整编译、展开、仿真和综合；功能 fixture 为 `Mismatches: 0`，并生成 `post_synth.dcp`、`timing.rpt` 和 `utilization.rpt`。
- 含真实 `clk` 端口的 fixture 按 5 ns（200 MHz）创建时钟约束并综合通过；`timing.rpt` 明确记录 `All user specified timing constraints are met.`。
- 负例：语法错误停在 compile；错误功能停在 simulation 并报告 `Mismatches: 2`。
- VerilogEval v2 测试台存在先使用后声明的模板写法；Vivado 2025.2 采用官方 `--relax` 选项后保持相同语义并可运行。
- Canonical Ubuntu 22.04.5 OCI rootfs 经 SHA-256 校验后导入 Docker。
- 最终 `amd-rtl-agent:dev` 镜像为 `sha256:a449bd5e2200162d42a34f57160fcaf56fe7dd857cc8de331f2ca37add80841f`，大小 `4,645,865,911` 字节；包含权重和 CPU llama.cpp runtime。
- `--network none` 下真实 7B 模型约 22.33 s 完成加载，`/health` 返回成功，最短聊天请求输出 `OK.`；同镜像的 mock baseline + 5 samples 冒烟也通过。
- 上述最短 CPU 请求生成约 7.10 tokens/s，只证明离线服务可用，不作为赛事 ROCm 性能或完整任务墙钟结论。
- VerilogEval v2 固定到 commit `c498220d0a52248f8e3fdffe279075215bde2da6`，共 156 组三元组。

真实 Qwen 7B CPU 开发烟测只验证端到端链路，不代表完整公开集或比赛成绩。每题仅取 1 个 agent 样本，因此只报告 pass@1，不报告 pass@5：

| 公开题 | baseline | agent pass@1 | agent 尝试数 | 总耗时 |
|---|---:|---:|---:|---:|
| `Prob001_zero` | 通过 | 通过 | 1 | 34.49 s |
| `Prob017_mux2to1v` | 通过 | 通过 | 1 | 78.00 s |
| `Prob024_hadd` | 通过 | 通过 | 1 | 59.39 s |

上述 3 个题面无歧义的烟测题均通过。它们是人为选择的小样本，不能外推为 VerilogEval pass rate。

另有两项上游数据一致性问题，保留原始失败结果但不混入上述烟测统计：

- `Prob031_dff` 题面写 `input q`，而参考实现和测试台要求 `output q`，导致严格按题面生成的 baseline/agent 出现 `120/121` mismatch。
- `Prob034_dff8` 题面没有规定初值，而参考实现包含 `initial q = 0`，测试台在首个有效更新前据此判定，导致 `1/41` mismatch。

智能体不读取参考实现或测试台源码。为增强对矛盾工具反馈的鲁棒性，修复阶段仅在日志明确称某端口为 `Output`、而候选把它声明为 `input` 时追加端口方向检查提示；没有题号或端口名特判。

尚未获得或不应声称的数据必须保留为空，而不是估算：

- 完整公开集 pass@1/pass@5：未运行；当前只有上表 3 题单样本 CPU 开发烟测。
- ROCm 显存、墙钟和稳定性：`pending_official_rocm_measurement`。
- 赛事方官方基础镜像、隐藏题集、最终调用器和时间预算：尚未发布，不能声称最终验收通过。

## 7. 已知失败与处理

- Codex 子进程缺少 `PROCESSOR_ARCHITECTURE` 会让 Vivado 批处理静默退出；`agent.py` 对所有子进程补 `AMD64`。
- 用户 TclStore App 会在批处理入口触发 `Common 17-356`；综合进程设置 AMD 支持的 `XILINX_LOCAL_USER_DATA=no`，不修改全局 TclStore。
- Windows 路径含空格时直接执行 `.bat` 会破坏参数；当前统一经 `cmd /c call` 运行。
- Docker Hub 在当前代理/DNS 下不可达；以 Canonical 官方 OCI rootfs 校验并 `docker import`，不依赖 Docker Hub。
- 首次增量安装因 AMD CDN 单个载荷 SSL/连接超时失败；脚本按最小改动增加有限重试后成功完成，目标器件计数和后续正式综合均已验证。

## 8. 复现

1. 运行 `tools/check_environment.ps1`。
2. 运行 `python -m unittest discover -s tests -v`。
3. 运行 fixture 的 `agent.py evaluate`。
4. 在 WSL 中运行 `tools/bootstrap_base_image.sh`、构建 Docker、运行 `tests/container_smoke.sh`。
5. 运行 `tools/download_model.sh`，核验 `model/MODEL.md` 中的 SHA-256。
6. 启动 `serve.sh`，先跑三个公开烟测题，再跑固定公开集。
7. ROCm 可用后只替换推理后端并填写实测字段；不得改写历史 CPU/Mock 结果。
