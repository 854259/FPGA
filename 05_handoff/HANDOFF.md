# 交接文档（脱敏版）

> **这是仓库内的脱敏副本。** 原始版本含实例地址、端口与密钥路径，只放在实例上
> （`/workspace/team/HANDOFF_20261002.md`）和团队本地，**不进公开仓库**。
> 本副本中所有地址、端口、密钥路径、主机指纹与公钥均已替换为占位符。
> 拿到实例访问权限的人请以实例上的原件为准。

---


- 时间：2026-10-02 14:30（Asia/Shanghai）
- 交接人：原会话 Agent
- 接手人：队友的 GPT
- **重要**：这是**脱敏副本**，可进公开仓库。含实例地址、端口、密钥路径的**原件**放在实例上（见文件开头说明），不要提交到公开仓库。

---

## 0. 怎么用这份文档

第 1–2 节给你背景，**第 6 节是全文最重要的部分**——那里记的是已经踩过的坑和已经推翻过的错误结论。**在动任何东西之前请先读第 6 节**，否则很容易重做已经做过的实验，或者相信已经被证伪的判断。

**2026-10-02 云端文档更正**：第 5、8 节保留早期 43 题参考检查与待跑计划，不是当前执行指令。后续 44 题配对已完成，但审计发现 12 契约问题、11 规格歧义、21 覆盖有限；详见 `03_analysis/rtllm_contract_audit_20261002/`。当前 AMD 契约修复与旧候选重判由既有本地任务负责，云端不重复启动。两题 pilot 仅为现场任务回报，见 `PROJECT_STATUS.md`，不是云端实测或新版全量成绩。

---

## 1. 项目背景（最小必要）

**比赛**：2026 全国大学生嵌入式芯片与系统设计竞赛 · FPGA 创新设计赛道（AMD）· **AMD 题目一「RTL/HLS 本地智能体设计赛道」的 RTL track**。队伍号 45561。

**任务本质**：做一个**本地、断网运行的 RTL 代码生成智能体**。赛事方从外部给我们的服务投题，我们返回 Verilog。

### 1.1 官方契约（固定，不可改）

- 官方仓库：Gitee `Vickyiii/rtlagent2026`，固定在 commit **`afd135e7ba5f6ec4c6d77e7c927c894327537801`**
- 协议：`GET /v1/health`（Bearer 鉴权，须返回 `track: "rtl"`）+ `POST /v1/solve`
- **只能绑 `127.0.0.1`**（平台 `rc-tunnel` 只接管环回口）
- 任何失败 = L0，**不重投**
- SIGTERM 须 10 秒内退出
- 官方 `baseline.py` / `run_baseline.sh` **队伍不得改动**（我们按字节固定并做 SHA-256 校验）

### 1.2 判定与计分

**分级**（递进）：L0 = 0，L1（编译过）= 0.2，L2（仿真过）= 0.7，L3（综合过）= 1.0。器件 `xczu3eg-sbva484-1-e`，周期 5 ns。

```
题集得分 = Σ系数 / 题数
能力分   = 30 × 题集得分
增益     = 方案得分 / 基线得分
增益分   = 40 · log(增益)/log(满分线)
代价     = 10 × min(基准时长 / 实测时长, 1)
总分权重 = 能力 30 + 增益 40 + 代价 10 + 工程质量 20
```

**几条关键细则**（都在 `04_project/amd_rtl_agent/official_reference/SCORING.md`）：

| 条 | 内容 | 我们现状 |
|---|---|---|
| 2.1 | 基于**官方基础镜像**构建、可独立重建 | ⚠️ 镜像**未公布**，见第 5.3 节 |
| 2.2 | 单卡、显存 ≤ 32 GB | ✅ 实测 19.0 GiB |
| 2.4 | `MODEL.md` 须声明模型来源/版本/量化/上下文，否则**增益 40 分不得分** | ✅ 已修 |
| 2.6 | 提交源码与技能包，否则工程质量 20 分不得分 | ✅ |
| 2.8 | 提交设计报告（含失败分析），否则工程质量按缺失折算 | ✅ 已重写 |
| 2.9 | 联网检索 / 硬编码答案 / 绕过模型 → **成绩作废** | ✅ 干净 |
| **基准时长** | **赛前公布，是固定值** | ⚠️ 未公布 |

**L1→L2 的系数跨度是 0.5，是分级表里最大的一级。** 官方原文：

> 「该级对应功能正确性的判定，而**参考测试台不予下发**，参赛智能体无法获得，**此为本赛道的核心考察点之一**。」

---

## 2. 一句话现状

**模型仍选 Qwen3.6-27B。7 规则独立实验记录 agent 0.7603 / baseline 0.6744、增益 1.1274；11 规则模型对照使用另一轮数据，见 3.2。RTLLM 历史 44 题为 0.5182 / 0.5591，但夹具与规格问题使泛化判断尚不成立。**

官方基础镜像与基准时长在本交接记录中仍待发布；此外，RTLLM 合同修复、歧义澄清及重判尚未全部完成。本次没有重新核查赛事公告。

---

## 3. 已完成并验证的

### 3.1 核心数据（公开集 VerilogEval v2 spec-to-rtl，156 题，单样本 pass@1）

| | agent | baseline |
|---|---:|---:|
| L3 | **111** | 98 |
| L1（仿真失败） | 38 | 36 |
| L0（编译失败） | **7** | 22 |
| 题集得分 | **0.7603** | 0.6744 |

能力分 **22.81**，增益 **1.1274**，能力+增益 **28.04**。
（上一轮 11 条规则时是 0.7269 / 增益 1.1031 / 合计 26.09。）

**关键结构性事实**：agent 的**功能失败数（38）比裸模型（36）还多 2 道**。它全部增益来自**编译层**（22→7），功能正确率没有改善。原因见第 4 节。

### 3.2 模型选择（11 规则模型 only 对照）

Qwen 运行 `amd156_20261001T075230Z`，iCoder 运行 `icoder_full156_20261001T141649Z`；同一 11 规则 skill，设计变量为模型权重。依据 `03_analysis/12_iCoder对照结果与结论_20261002.md`。

| | Qwen3.6-27B | iCoder-27B（RTL 专精） |
|---|---:|---:|
| baseline 得分 | 0.6590 | **0.7564** |
| agent 得分 | 0.7269 | 0.7679 |
| **增益** | **1.1031** | 1.015 |
| 能力+增益（满分线占位 2.5） | **26.09** | 23.69 |

上述占位满分线下，Qwen 的能力 + 增益合计较高，保留 Qwen3.6-27B 的决定不变；这不是正式总分结论。**7 规则为独立实验**（`skillfix_full156_20261001T235258Z`）：agent **0.7603** / baseline **0.6744**、增益 **1.1274**、能力 **22.81**、占位合计 **28.04**，不得混入本模型对照表。依据 `03_analysis/13_Skill精简对照结果_20261002.md`。

### 3.3 技能包

`skill/rtl-generation/SKILL.md`（7 条规则，1071 B，sha256 `f4c4c8e2…`）+ `skill/rtl-feedback-repair/SKILL.md`（1162 B，`aee81f18…`）。

**两次独立实验都证明：规则越少越好。**

| 版本 | 40 题 A/B | 156 题 agent 得分 |
|---|---:|---:|
| 7 规则 | **17/40** | **0.7603** |
| 11 规则 | 11/40 | 0.7269 |

规则 1–7 在两版里**字节完全相同**，所以全部差异来自删掉的 8–11 条。
**纪律：技能文本必须短；除非有证据，不要加规则。**

### 3.4 提交包

`04_project/amd_rtl_agent/submission/` **就是官方 `<team_name>-agent/` 布局**，12 项 §5.1 条目齐备：
`agent/runtime.py`、`skill/rtl-generation/SKILL.md`、`skill/rtl-feedback-repair/SKILL.md`、`skill/README.md`、`serve/llama.sh`、`serve/README.md`、`manifest.json`、`Dockerfile`、`model/MODEL.md`、`REPORT.md`、`run.sh`、`baseline.py`。

**验证**（实跑，非目视）：

- `reference3`：3/3 L3
- `smoke3`：agent 3/3 L3、baseline 3/3 L3，零工具错误

**踩过的坑**：把 `runtime.py` 移进 `agent/` 后 `import baseline` 失效（`sys.path[0]` 从包根变成 `agent/`），首次验证 agent 得 **0.0000**。已修（加 `PKG` 探测 + 注入 `sys.path`）。**教训：包结构必须实跑验证，看是看不出来的。**

### 3.5 其它已归档

- `Dockerfile` 已按官方模式参数化（`ARG BASE_IMAGE` + 占位符），**但无法构建**（镜像未公布）
- `05_handoff/BUILD_CHECKLIST_20261002.md`：镜像公布后照着做的 12 条验证清单
- `model/MODEL.md`：已声明 `ggml-org/Qwen3.6-27B-GGUF` @ `8a7ee08e`、Q4_K_M、sha256 `65b753ea…`、上下文 16384 / 输出 8192 / 温度 0、实测显存 19.0 GiB（gfx1100 开发卡，**非决赛卡**）
- `REPORT.md`：11 节设计报告，含失败分析
- 官方契约、赛道指南、官方范例 Dockerfile 全部存档在 `official_reference/`

---

## 4. 核心问题：agent **发现不了**功能错误

这是目前最重要的技术事实，也是下一步工作的焦点。

### 4.1 现状

`agent/runtime.py` 的检查**只跑 `xvlog`（编译分析）**，没有 `xelab`，没有 `xsim`。代码注释原文：

```python
if result.returncode == 0:
    return  # Compilation is NOT an official L1/L2/L3 judgement.
```

所以：

| 错误类型 | 能发现吗 | 能修吗 |
|---|---|---|
| 格式错（缺 `endmodule`） | ✅ 结构检查 | ✅ 重新生成 |
| 声明错（`VRFC 10-1280`） | ✅ `xvlog` | 仅带候选诊断让模型再生成；当前 runtime 无声明自动补丁 |
| 其他编译错 | ✅ `xvlog` | ✅ 带日志重新生成 |
| **功能错** | ❌ **无任何手段** | — |

**它不是"看到错了改不动"，是"根本不知道自己错了"**，于是认为一切正常、直接交卷。那 38 道仿真失败的题，对它来说**全都是一次成功**。

### 4.2 讽刺的是，修复提示词早就写好了

`RTL_REPAIR_SKILL.md` 第 3 条原文：

> 「若**已进入仿真且 Mismatches 非零**，先检查反馈中的候选位宽/截断警告，再核对复位、使能与加载优先级、非阻塞赋值旧值、输出延迟、计数首末拍及状态表。」

**这段提示词从没被执行过**，因为仿真那一步不存在。历史上旧版 `agent.py` 有完整链路 `xvlog → xelab → xsim → synth_design`，是官方契约版把它去掉了（官方不给测试台）。

### 4.3 为什么必须由模型来产生"真值"

判断功能对不对需要两样东西：

| 要素 | 难吗 |
|---|---|
| 激励（把输入喂进去） | ❌ 不难，**纯机械**（`bench/build_rtllm_taskset.py` 里就有这个生成器） |
| **真值来源**（输出应该是什么） | ✅ **这才是难点** |

所以准确说法**不是"必须写测试台"，而是"必须有真值来源"**。真值只存在于题面（自然语言）→ 只有模型能解读 → 所以模型必须产出**预期值（测试台）**或**一份独立实现（参考）**。

### 4.4 已排除的路（不要重做）

**❌ 静态诊断（本以为免费）——已实测证伪**

我本以为能让编译器告诉我们哪里可能错。**实测否定**：

- `xvlog`：编译成功的题**零 RTL 警告**，只有 locale 噪声（`WARNING: The locale 'C.utf8' is not installed`——**这条是每条 xvlog 都打的，别把它当信号**）
- `xelab`（细化）：**零有效诊断**，只有 C 编译器环境变量警告

**含义**：这些失败的设计**不是"写得不规范"，而是"逻辑就是错的"**——代码干净、语法正确、细化无问题。静态工具看不见功能。

**⚠️ 我在这一点上犯过一个错**：我先跑出一个"151/156 道题有警告"的结果，其实那全是 locale 噪声，被我当成了信号。**看到"有警告"先确认警告内容，不要只看计数。**

### 4.5 还剩两条路

**路 A：独立二次实现 + 机械双例化比对**（我建议先试这条）

```
题面 ──> 实现 1（候选）
   └──> 实现 2（独立再写一遍）
              ↓
   机械生成的双例化测试台（不用模型写！）
   随机激励下比对两份实现 → 不一致 = 至少一份错
```

**优势**：模型只需写 **RTL**（它擅长），**不需要写测试台**（它不擅长，见下）。双例化生成器已存在。
**前提**：`temperature` 必须非零，否则两次生成完全相同。

**路 B：模型自写测试台**

官方点名的核心考点。但**探针实测只有 37.5% 可用**（8 题里 3 题能区分对错、3 题测试台自己编译失败、2 题把正确的参考解也判错）。

### 4.6 共同的根本局限（必须说清）

两条路都依赖**同一个模型对题面的理解**。若模型**一致地误解**题面，两份实现会错得一样、测试台也按同样误解写 → **抓不到**。

**所以功能自检能降低错误率，但降不到零。** 这是天花板，不是实现问题。

### 4.7 ⚠️ 一个重要的代价权衡

```
代价 = 10 × min(基准时长 / 实测时长, 1)     基准时长赛前公布，是固定值
```

- 实测：agent 均 **19.75 s/题**，我们自己的 baseline 均 16.58 s → 比值 0.84 → **代价约 8.40/10**
- 加自验证要 **+38 s/题** → 比值掉到 ~0.29 → **代价约 2.9（−5.5 分）**
- 要靠能力分补回 5.5 分需要修好 **约 36 道题**（我们只有 38 道 L1）——**不可能**

**但这个算式有个未知数**：`基准时长` 是官方公布的固定值，我们不知道它多大。若公布值宽松，加了 38 秒仍比它快，则代价照样满分、自验证白赚。

**所以自验证不是"确定亏"，是"赌一个未公布的数"。**

---

## 5. 历史记录：RTLLM 初版参考检查与泛化计划

本节保留早期 43 题结果及当时计划。后续固定分母为 44，配对已完成；原“增益消失即过拟合”的判读撤回，夹具合同尚未成立时不能如此归因。现状以本文第 0 节与审计入口为准。

### 5.1 为什么做这个

官方评测题集**赛前不公开**，且只有"**部分**与公开基准同源"。而我们全部调优都建立在 VerilogEval 那 156 题上。**如果隐藏集重点不同，我们可能一直在优化不会出现的东西。**

所以：拿一套**与 VerilogEval 无重叠**的题重跑配对，看增益能不能迁移。

### 5.2 现状

- **题集**：RTLLM v2.1，commit `51ed553d0ffd32797a1a0a13e051656bf302c81f`，MIT 许可，50 个设计
  - 题域与 HDLBits 完全不同：RISC-V ALU / 寄存器堆、FIFO、Booth 乘法器、交通灯、串并转换……
  - `design_description.txt` 含模块名 + 完整端口表（名字/位宽/含义）；有 50 份人工参考实现
  - **其自带测试台不能用**（单例化 + 弱判据），已重新生成双例化版本
- **转换器**：`04_project/amd_rtl_agent/bench/build_rtllm_taskset.py`
- **参考自检结果**（已完成，证据在 `bench/rtllm_refcheck_20261002/graded_summary.json`）：

| | |
|---|---|
| **set_score** | **0.9860** |
| L3 | **41** |
| L2（功能过、综合没过） | 2（`float_multi`、`synchronizer`） |
| **可用题** | **43** |
| 剔除（工具错误） | 6：`adder_pipe_64bit`、`asyn_fifo`、`fixed_point_adder`、`fixed_point_substractor`、`multi_pipe_4bit`、`multi_pipe_8bit` |

**那 6 题是流水线/定浮点/异步 FIFO 类，我们生成的测试台对它们不成立**，需要修或直接剔除。

**⚠️ 转换时踩的坑（已修）**：RTLLM 时钟/复位命名极不规范（`clk` `CLK` `Clk` `CLK_in` `clk_a` `clk_b` `wclk` `rclk`；`rst` `RST` `Rst` `rst_n` `arstn` `brstn`）。第一版只匹配小写 `clk`，导致 **10 道时序题没有时钟**。**如果不修，参考实现永远不推进、被判失败，而会误以为是"模型不行"。**

### 5.3 下一步（**未做**）

跑 `agent` / `baseline` 配对，与 VerilogEval 的增益 **1.127** 对比。

- 增益还在 → skill 是通用的，可以继续优化
- 增益消失 → 说明在 VerilogEval 上过拟合，**先让 skill 泛化，别再调优**

### 5.4 另一条并行线：官方基础镜像

**三个 Gitee 仓库都没有镜像**（`fpgachina26-amd` 是索引仓库、`rtlagent2026` HEAD 与我们固定的完全一致、`hlsagent2026` 是 HLS track 的）。

官方范例里镜像名是**占位符**：
```
ARG BASE_IMAGE=fpgachina2026/base-gfx1100:REPLACE_WITH_ANNOUNCED_TAG
```
两个变体：`gfx1100`（验证窗口，W7900）与 `gfx1201`（决赛，R9700）。**正式名字在验证窗口前公布。**

**镜像公布前 2.1 条没有任何可推进动作**，只能等。

---

## 6. ⚠️ 必须知道的坑与已推翻的结论

**这一节最重要。下面每一条都是我实际犯过或证伪过的，请勿重犯。**

### 6.1 方法论纪律

| 坑 | 事实 |
|---|---|
| **跨轮变化不是噪声模型** | baseline 不读 skill，旧、新 VerilogEval 两轮仍有 **5/156（3.2%）变化**。原因未定位；多线程归约仅是待验证解释。不能据此计算 RTLLM 44 题的方差、1.25σ 或“在噪声内”，净变化也不能替代预定重复协议。 |
| **一次只改一个变量** | 不要在同一个实验里同时改 skill 和模型。 |
| **参考自检是必要但不充分的检查** | 参考自检可暴露工具、转换或参考异常，但通过也不能证明合法域、参数、复位、时序与 oracle 正确；须另做合同审计及有效正负控。云端只读，实际验证由授权 AMD 任务执行。 |
| **包结构必须实跑验证** | 见 3.4，目视检查发现不了 `import baseline` 失效。 |

### 6.2 我做错并已修正的判断（**不要沿用旧说法**）

| 我曾经的说法 | 实际 |
|---|---|
| "提交包缺文件 = 工程质量 20 分悬崖" | ❌ 错。2.6 要的是**源码 + 技能包**，我们本来就有。真正的悬崖是 **2.4 的 40 分**（`MODEL.md` 未声明），而当时 `MODEL.md` 确实过期了 |
| "自验证净负 −4 分，确定不要做" | ⚠️ **说得太满**。取决于未公布的基准时长，可能 +1~2 也可能 −4。但**测试台可用率只有 37.5%** 是更实在的障碍 |
| "加 skill 规则 8–11 使 baseline 变差" | ❌ 错。**baseline 从不读 skill**，那时的波动是噪声 |
| "L0 快 = 空响应" | ❌ 错。`Prob034_dff8` 产出了 62 token / 148 B，不是空的；2 秒的 L0 是**编译早期失败** |
| "磁盘会撞 8 GiB 下限" | ❌ 错。整个运行目录才 ~5 MB |
| "iCoder 输出更短" | ⚠️ 只在最初 22 道简单题成立；全量上 iCoder 输出更长（845/911 vs 520/504 token） |
| "15 分钟没进展，worker 疑似卡死" | ❌ 错。当时只过了 39 秒 |
| "151/156 道题有编译警告（免费信号）" | ❌ 错。全是 locale 噪声，见 4.4 |
| "自验证可以先做起来" | ❌ 顺序错了。**应该先用官方测试台当"完美预言机"测上限**，见第 8 节 |

### 6.3 其它技术坑

| 坑 | 处理 |
|---|---|
| 思考块吃掉输出 | Qwen 系模板默认输出 `<think>`。`--reasoning off` 后截断率从 **37.1% → 1.8%** |
| 官方 `score.py` 在 Windows GBK 控制台崩（`−` U+2212） | 加 `PYTHONIOENCODING=utf-8`（Linux 不受影响） |
| `trace.jsonl` 的判别字段是 **`tool`**，不是 `event` | 用错会解析出 0 条记录 |
| `official_eval.py` 在启动时锁定题单 | 跑起来之后新增的题不会被包含 |
| `ref.sv` 定义 `RefModule`；参考解在 `<task>/reference/solution.sv` | 别搞混 |
| PowerShell 里 `$P`、`\$P` 会被吃掉 | 用 base64 把脚本塞进 `/tmp/*.sh` 再 `bash` 跑，最稳 |
| SSH 会瞬断 | `nohup` 起的任务不受影响，重连后继续 |

---

## 7. 硬约束

1. **实例永远不要关闭**（用户明确要求过）。`root@<INSTANCE_HOST>:<INSTANCE_PORT>`，密钥 `<SSH_KEY_PATH>`
2. 实例上 `llama-server` 正在运行（PID 1198635，`Qwen3.6-27B-Q4_K_M`，端口 8000）——**不要重启它**，除非确认要重载
3. **不要改官方 `baseline.py` / `run_baseline.sh`**（按 SHA-256 校验，改了会被 `baseline_integrity()` 拒绝）
4. **不做触红线的事**：不联网检索、不硬编码题解、不绕过模型
5. 长任务一律 `nohup` 起，避免 SSH 瞬断杀掉
6. 实例**没有直连外网**，要走平台代理：`HTTPS_PROXY` 在 `/proc/1/environ` 里（**交互式 shell 的 `env` 看不到**）。`hf-mirror.com` 可用
7. 模型/技能**一次只改一个变量**，且必须与基线做配对比较

### 7.1 队友的实例账号（已配好：**root，与本人相同**）

团队决定给队友**与本人完全相同的 root 权限**，各自持有自己的密钥（不共享私钥）。

**当前 `/root/.ssh/authorized_keys` 有 2 把钥匙**（`chmod 600`，目录 `700`）：

| 指纹 | 归属 |
|---|---|
| `<USER_KEY_FPR>` | 本人（`amd-shared-20261001`） |
| `<TEAMMATE_KEY_FPR>` | 队友（`teammate`） |

队友登录：

```bash
ssh -i ~/.ssh/<TEAMMATE_KEY> -p <INSTANCE_PORT> root@<INSTANCE_HOST>
```

**首次连接会停在主机身份验证**（`The authenticity of host ... can't be established`）。**这一步在认证之前**，与钥匙无关。核对指纹一致后输 `yes`。

**⚠️ 这台机器上跑着两套 sshd，只有一套对外服务：**

| | 路径 | 用途 |
|---|---|---|
| **实际服务** | `/tmp/amd-oneclick-sshd_config`（`sshd -f` 指定），HostKey 指向 `/run/amd-oneclick-ssh-host-keys/` | ✅ **客户端看到的就是这套** |
| 未被使用 | `/etc/ssh/ssh_host_*` | ❌ 发行版默认密钥，`/etc/ssh/sshd_config` 并未对外生效 |

**对外正确的主机密钥指纹**（主机名 `<HOSTNAME>`）：

| 类型 | 指纹 |
|---|---|
| **ED25519** | `<ED25519_HOST_KEY_FPR>` |
| **RSA (3072)** | `<RSA_HOST_KEY_FPR>` |

**不要使用 `/etc/ssh/` 下那套指纹**（`<UNUSED_HOST_KEY_FINGERPRINTS>`；具体值仅保留私有原件）——那是未被使用的密钥，照它核对会误判为指纹不符并中断连接。

**判断依据（三重印证）**：`~/.ssh/known_hosts` 里本人成功连接的记录、队友客户端实际收到的值、以及服务器 `sshd -T` 显示的 HostKey 路径，三者一致。

想免掉提示，可把 `[<INSTANCE_HOST>]:<INSTANCE_PORT>` 的 `ssh-ed25519` 条目预写进 `~/.ssh/known_hosts`。

**⚠️ 两人都是 root，必须约定不要同时跑全量评测。** 同机抢 GPU 与 128 核会污染双方结果（旧两轮的 5/156 变化不能作为稳定噪声率）。约定分开工作目录：本人用 `/workspace/team/runs/fpga_owner/`，队友用 `/workspace/team/runs/fpga_teammate/`（已创建，`2775`，属主 `fpga_teammate:fpga`）。

**备用受限账号**：实例上另有 `fpga_teammate` 账号（uid 1002，主组 `fpga`，**无 sudo**）。实测可读官方 kit / RTLLM 题集 / 模型权重 / Xilinx 许可证 / Vivado，可跑 `xvlog`（Vivado Simulator v2026.1），可连 `127.0.0.1:8000`，可写 `/workspace/team/runs/fpga_teammate/`。该账号的 `authorized_keys` 目前为空；保留作备用入口。

**踩过的坑（重要）**：

1. **`authorized_keys` 末尾原本没有换行符**，直接 `>>` 追加会把两把钥匙**拼成一行**，第二把沦为第一把的注释而完全失效。**追加前必须先确保末尾有换行**，或改用「读取 → 逐行 strip → 去重 → 重写」的方式。
2. **不要从截图转录公钥。** 本次从截图抄错 2 个字符（第 36 位 `C`→应为 `G`、第 52 位 `c`→应为 `G`），装上去后指纹不符。**公钥必须以纯文本传递**，并用 `ssh-keygen -lf` 与对方报告的指纹核对后再算完成。
3. `ssh-keygen -lf` 对空文件会报 `is not a public key file`，那是正常的空文件提示，不是错误。
4. **公钥不能用来登录**：必须本人生成密钥对，把公钥装到服务器，用**自己的私钥**登录。任何情况下都不要传私钥。

---

## 8. 历史建议（保留记录，不作为当前执行授权）

以下命令、43 题分母和判读表是早期方案，不得据此重复启动既有 AMD 任务。先完成合同修复与候选重判；新增题面要求须两侧重新生成或生成前排除，不按已见分数挑选子集。旧“增益 >1.05 即通用 / 接近 1 即过拟合”规则不成立。

### 第 1 步（**最高优先**）：跑通 RTLLM 泛化验证

题集已就绪（43 题可用），参考自检已通过。跑 `agent` / `baseline` 配对，与 **1.127** 对比。

**这一步决定后面所有工作是否有效。** 若增益迁移不过去，第 2、3 步都是白费。

**可直接执行的命令**（在实例上跑；注意 `nohup`，SSH 会瞬断）：

```bash
cat > /workspace/team/rtllm_pair.py <<'PYEOF'
import json, os, pathlib, subprocess, datetime
P  = pathlib.Path("/workspace/team/tasks/autodl-rtl-kit/project")
RR = pathlib.Path("/workspace/team/runs/fpga_owner/rtllm_pair_20261002")
RR.mkdir(parents=True, exist_ok=True)
scratch = RR / "scratch"; scratch.mkdir(exist_ok=True)
ENV = os.environ.copy()
ENV.update(
    PATH="/workspace/AMD/2026.1/Vivado/bin:" + ENV["PATH"],
    LD_LIBRARY_PATH="/workspace/team/udev-stub",
    XILINXD_LICENSE_FILE="/workspace/team/Xilinx.lic",
    XILINX_VIVADO="/workspace/AMD/2026.1/Vivado",
    LLM_BASE_URL="http://127.0.0.1:8000/v1",
    MODEL_NAME="Qwen3.6-27B-Q4_K_M",
    RTL_PROFILE="development", RTL_REPAIRS="1",
    RTL_MAX_TOKENS="8192", RTL_TEMPERATURE="0",
    EDA_TMP=str(scratch), SELFTEST_TMP=str(scratch),
    NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost",
)
out = RR / "pair"
args = ["python3", "-B", str(P / "official_eval.py"),
        "--tasks", "/workspace/team/tasks/rtllm",
        "--out", str(out), "--samples", "1", "--deadline", "300"]
print("start", datetime.datetime.now().isoformat(), flush=True)
p = subprocess.run(args, cwd=P, env=ENV, capture_output=True, text=True, errors="replace")
print("rc =", p.returncode)
if p.returncode != 0:
    print((p.stdout + p.stderr)[-2000:])
else:
    d = json.loads((out / "graded_summary.json").read_text())
    for m, s in d["modes"].items():
        print("  %-9s set=%.4f levels=%s tool_errors=%d"
              % (m, s["set_score"], s["level_counts"], s["tool_errors"]))
    a = d["modes"]["agent"]["set_score"]; b = d["modes"]["baseline"]["set_score"]
    print("  增益 = %.4f   (VerilogEval 上是 1.1274)" % (a / b if b else 0))
PYEOF
cd /workspace/team && nohup python3 -u rtllm_pair.py > rtllm_pair.log 2>&1 &
```

**怎么判读结果**：

| 增益 | 含义 | 行动 |
|---|---|---|
| 仍明显 > 1（如 >1.05） | skill 是通用的 | 继续按第 3、4 步优化 |
| 接近 1.0 | **在 VerilogEval 上过拟合** | 先让 skill 泛化，**停止第 3、4 步** |
| < 1.0 | agent 反而更差 | 排查是否转换/环境问题，再下结论 |

同时看 `baseline` 的绝对分：若 baseline 接近 0（RTLLM 对 27B 太难），增益会变成 0/0 无意义，**那时只比绝对分，不比增益**。

**⚠️ 用之前先处理那 6 道被剔除的题**（`adder_pipe_64bit`、`asyn_fifo`、`fixed_point_adder`、`fixed_point_substractor`、`multi_pipe_4bit`、`multi_pipe_8bit`）：它们在参考自检里就是工具错误，跑配对时会作为工具错误被自动排除（`scored_tasks` 会少于 49）。**这是已知的、可接受的**，但要知道分母是 43 而不是 49。

### 第 2 步：用"完美预言机"测功能反馈的上限

**在我之前想的"先做测试台生成器"之前，应该先做这个**——成本约 30–60 分钟、纯离线、零风险：

```
拿 38 道 L1 失败题
  → 把【官方测试台的 mismatch 反馈】直接喂进修复循环
  → 按 RTL_REPAIR_SKILL.md 第 3 条修，最多 3 轮
  → 看有多少达到 L3
```

| 结果 | 决策 |
|---|---|
| 修好很多（如 20/38） | 功能反馈是真金 → 投入做 4.5 节的**路 A** |
| 修好很少（如 3/38） | **连完美反馈都救不动** → 两条路都不做，省下几天 |
| 中等 | 按比例折算决定投入 |

**注意**：这个实验在正式比赛里做不了（官方不给测试台），它只是**用来测上限**。

### 第 3 步：代价项调优（+1.6 分，无正确性风险）

实测生成速度 **29 tok/s**。模型 19 GB、W7900 带宽约 864 GB/s → 理论上限约 **45 tok/s**，我们只跑到 64%。

因为基准时长是**固定公布值**，**我们绝对越快，代价分越高**。调 `llama.cpp` 的 flash-attention / batch / ubatch 可能显著改善。

### 第 4 步：技能精细改动（靶子已明确）

- `Prob150_review2015_fsmonehot`（漏下一状态自环）、`Prob154_fsm_ps2data`（数据通路未覆盖绕过中间状态的转移）
- **4 道模型无关回归题**（`Prob094` `Prob143` `Prob150` `Prob154`）——在 Qwen 和 iCoder **两个完全不同基座上都回归**，因此归因于提示而非模型，共同特征是"长篇逐项枚举时漏项"
- 纪律：**一次一条，先跑子集预筛，不显著就回退**

### 第 5 步：官方基础镜像到位后

照 `05_handoff/BUILD_CHECKLIST_20261002.md` 执行（12 条验证判据 + 已知构建陷阱）。

---

## 9. 关键坐标速查

### 本地

| 内容 | 路径 |
|---|---|
| 仓库（git） | `E:\26qiansai\FPGA-official-contract`，分支 `feat/official-rtl-contract` |
| 远端 | `https://github.com/854259/FPGA.git` |
| 最新提交 | `9a5c584`（RTLLM builder + refcheck） |
| 提交方案包 | `04_project/amd_rtl_agent/submission/` |
| 官方契约与指南 | `04_project/amd_rtl_agent/official_reference/` |
| RTLLM 源与生成题集 | `E:\26qiansai\rtllm-gen\` |
| 分析报告 | `03_analysis/11_*` `12_*` `13_*` |

### 实例（`root@<INSTANCE_HOST>:<INSTANCE_PORT>`）

| 内容 | 路径 |
|---|---|
| 官方 kit（含判定器） | `/workspace/team/tasks/autodl-rtl-kit/project/` |
| VerilogEval 156 题 | `<kit>/bench/tasks_veval/` |
| RTLLM 题集（49 题） | `/workspace/team/tasks/rtllm/` |
| 模型 | `/workspace/team/models/Qwen3.6-27B-Q4_K_M.gguf` |
| llama.cpp | `/workspace/team/tools/llama-build/bin/llama-server` |
| 历次运行 | `/workspace/team/runs/fpga_owner/` |

### 关键运行目录

| 运行 | 目录 |
|---|---|
| Qwen 全量 156（7 规则，当前最好） | `runs/fpga_owner/skillfix_full156_20261001T235258Z/` |
| Qwen 全量 156（11 规则） | `runs/fpga_owner/amd156_20261001T075230Z/` |
| iCoder 全量 156 | `runs/fpga_owner/icoder_full156_20261001T141649Z/` |
| 打包验证 smoke3 | `runs/fpga_owner/pkgvalidate2_20261002/` |
| RTLLM 参考自检 | `runs/fpga_owner/rtllm_refcheck_20261002/` |

---

## 10. 一句话给接手人

先读 `03_analysis/rtllm_contract_audit_20261002/` 与 `PROJECT_STATUS.md` 的最新更正。44 题旧分数保留，但不能代表可靠泛化结果；AMD 修复与重判由既有任务负责，云端仅做文档编辑与静态审查，不重复运行第 8 节历史计划。
