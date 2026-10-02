> **脱敏副本。** 原件含实例地址与端口，放在实例上 `/workspace/team/STATUS_LATEST.md` 和 `/workspace/team/runs/fpga_teammate/STATUS_LATEST.md`。

---

# 最新状态交接（2026-10-02 19:10 Beijing）

- 写给：队友（以及他的 GPT）
- 作者：原会话 Agent
- **这份文档的目的是让你不用问我任何问题就能接手。** 我做的每一件事、每个未完成的实验、每个未提交的改动，全在这里。

---

## 0. 三十秒看懂

**你之前那轮 RTLLM 配对测出增益 0.9268（agent 比 baseline 差），我去查了原因。**

查到两件事：

1. **一个具体的管道盲区**：agent 的自检只跑 `xvlog`，抓不到"实例化了未定义的子模块"——那要 `xelab` 才报。**你的 44 题里，agent 的 10 道 L0 有 5 道是这一类。**
2. **一个可修复的方向**：我加了 `xelab` 检查，跑了 **42/88 个样本就被叫停**，结论未定。已知回收率 25%，而代价项约 −0.46 分，**大致打平**。

**现在实例是干净的**：`runtime.py` 已还原为原始版，没有进程占用，服务空闲。**你可以直接开工。**

---

## 1. 我改了实例上的文件吗？——改过，已经还原

| 文件 | 现在状态 |
|---|---|
| `/workspace/team/tasks/autodl-rtl-kit/project/submission/agent/runtime.py` | ✅ **原始版**，sha256 前缀 `82e3a72e` |
| 同上 `.pre-xelab.bak` | 我改动前的备份（内容与上面相同） |
| 同上 `.my-xelab-version` | 我改的版本（含 xelab），**实例上当前不生效** |

**我改了什么**：在 `xvlog` 通过后加了一段 `xelab TopModule -s candidate_N --nolog`，失败就把错误喂进修复循环。

**还原验证过**：`grep -c xelab` 返回 0，sha256 与我接手前一致。

**所有版本备份**（4 份，都在下面第 6 节列了路径）。

---

## 2. 我跑过的实验（完整清单）

| 实验 | 状态 | 结果 |
|---|---|---|
| RTLLM 参考自检（我第一版题集，49 题） | ✅ 完成 | set_score 0.9860，L3 41 / L2 2，**6 道工具错误** |
| 后被你重做并修正 | ✅ | 44 题、0 工具错误、0.9864 |
| **RTLLM 配对（你的）** | ✅ 完成 | agent 0.5182 / baseline 0.5591，**增益 0.9268** |
| **加 xelab 后再跑配对** | ⚠️ **中途叫停** | **42/88 样本**，未完成，**结论未定** |
| VerilogEval 上的细化失败普查 | ✅ 完成 | 156 题里只有 **1 道** `xvlog` 过而 `xelab` 挂 |
| `xelab` 耗时测量 | ✅ 完成 | **1.12 秒/题**（`xvlog` 是 1.07 秒） |
| L0 失败分类 | ✅ 完成 | 见第 3 节 |
| 修 `runtime.py` 引入的 `import baseline` 失效 | ✅ 完成 | 见 `HANDOFF_20261002.md` 3.4 节 |

---

## 3. 我查到的确切事实（可直接引用）

### 3.1 盲区：`xvlog` 看不见未定义子模块

RTLLM 的题面常引导层次化设计（"用 8 位块搭 16 位加法器"）。模型会写：

```verilog
module TopModule ( ... );
    adder_8bit u0 ( .a(a[7:0]), ... );   // ← 从未定义 adder_8bit
```

**`xvlog` 返回 0（成功）**，因为它是单文件分析，不解析模块实例化。
**`xelab` 才报**：`ERROR: [VRFC 10-2063] Module <adder_8bit> not found while processing module instance <u0>`

后果链：agent 以为成功 → 交卷 → 判定器细化失败 → L0 → **修复循环从不触发**。

### 3.2 分类结果（我逐题实跑 `xvlog` + `xelab` 得出）

| 模式 | L0 总数 | `xvlog` 就报错 | **`xvlog` 过、`xelab` 挂** |
|---|---:|---:|---:|
| **agent** | 10 | 5 | **5** |
| baseline | 9 | 3 | **6** |

agent 那 5 道：

| 题目 | `xelab` 报的缺失模块 |
|---|---|
| `adder_16bit` | `adder_8bit` |
| `adder_32bit` | `cla_16bit` |
| `barrel_shifter` | `mux2X1` |
| `div_16bit` | `div_16bit` |
| `multi_pipe_8bit` | `TopModule` |

**注意 baseline 也有 6 道同类**——说明这是模型的普遍行为，不是 agent 独有。差别在于：baseline 没有修复循环，agent 有但没被触发。

### 3.3 已验证：`ref.sv` 里辅助模块是定义了的

`adder_16bit/ref.sv` 里定义了 `add8_rtllm_ref`、`add4_rtllm_ref`、`add2_rtllm_ref`、`add1_rtllm_ref`。

**所以题目是完好的，是模型自己的问题**——不是题目缺失定义。

### 3.4 VerilogEval 上这个检查几乎不触发

| VerilogEval agent 解答（156 题） | 数量 |
|---|---:|
| `xvlog` 失败 | 5 |
| **`xvlog` 过、`xelab` 挂** | **1**（`Prob156_review2015_fancytimer`） |

**含义**：加这个检查在 VerilogEval 上几乎不改变行为（只多 1 次修复），主要收益只在 RTLLM 这类层次化题上。

### 3.5 成本实测

```
xvlog  平均 1069 ms/题
xelab  平均 1121 ms/题
```

按 VerilogEval 的 agent 均 19.75 秒算：`19.75 → 20.87`，代价比值 `0.840 → 0.794`，
**代价项 8.40 → 7.94，即 −0.46 分**。

### 3.6 实验中途数据（42/88，**不要当结论**）

| 题目 | elab 各轮 rc | 结果 |
|---|---|---|
| `JC_counter` / `LFSR` / `accu`（及多数其他题） | `[0]` | 一次过 |
| `barrel_shifter` | `[1, 0]` | ✅ **修复成功** |
| `adder_16bit` | `[1, 1]` | ❌ |
| `adder_32bit` | `[1, 1]` | ❌ |
| `div_16bit` | `[1, 1]` | ❌ |

**回收率 1/4 = 25%。**

---

## 4. 我没做完的（你可以接着做）

### 4.1 加"针对性修复提示"的 A/B ← 我建议先做这个

**假设**：`barrel_shifter` 能修好、`adder_16bit` 修不好，差别在于模型第二轮有没有意识到"得把子模块定义出来"。

**做法**：在细化失败时，往反馈里追加一句：

> 「你实例化了未定义的子模块。请把所有被实例化的模块定义在同一文件里，或改写成不含子模块的扁平实现。」

**验证方式（很便宜，约 5 分钟）**：只挑那 5 道细化失败题重跑——同题、同温度（0），只差那句提示。直接对比第二轮结果。

**不需要跑全量 88 个样本。**

**代码位置**：`runtime.py` 里 `trace(out, 'elab', ...)` 之后、`if result.returncode == 0:` 之前，往 `feedback` 追加。

### 4.2 端口一致性审计 ← 我认为这个更重要

**核对 RTLLM 每道题的"描述端口表"与"参考实现端口"是否一一对应。**

- 一致 → 题目没问题，你那个"增益没迁移"的结论更硬
- **不一致 → 是题目冤枉了模型**，这直接改变结论性质

我抽查过 `adder_16bit`（描述 `a[15:0] b[15:0] Cin y[15:0] Co` vs ref 完全相同），但**没做全量**。

约 10 分钟，纯 CPU。

### 4.3 把 xelab 实验跑完

如果你判断值得，版本都在（见第 6 节）。跑全量约 95 分钟。

**但要先确认单变量纪律**：先做 4.1，再决定要不要合并两者一起跑。

---

## 5. 必须避免的误读

| 别这么说 | 应该说 |
|---|---|
| "RTLLM 上 agent 比 baseline 差" | **"没检测到增益"**——44 题里 2 道差距 ≈1.25σ，**在噪声内**（本底噪声约 3.2%/题） |
| "证明我们的 skill 不泛化" | "增益未能复现，是**值得警惕的信号**，样本量不足以下定论" |
| "隐藏题集也会这样" | **完全未知**。官方只说"部分与公开基准同源" |
| "RTLLM 题目质量有保证" | 它是学术基准且有已知瑕疵——我第一版 6 道工具错误、你另排除 5 道 |

**另外**：RTLLM 的核心价值是**配对比较**（agent 和 baseline 面对同一参考、同一测试台），所以题目瑕疵对双方的打击是对称的——这也是"增益没复现"这个结论仍然站得住的原因。

---

## 6. 所有文件位置

### 6.1 我的实验目录

```
/workspace/team/runs/fpga_owner/rtllm_xelab_20261002/
├── NOTE_FOR_TEAMMATE.txt          我留的现场说明
├── run_meta.json                  实验配置（runtime 哈希、参数）
├── pair/                          42/88 的未完成结果
├── runtime.original.py            原始版（= 实例当前生效版）
├── runtime.xelab.py               我改的版（含 xelab）
├── runtime.py.pre-xelab.bak       实例上的原始备份
└── runtime.py.my-xelab-version    实例上我改的版（双保险）
```

### 6.2 你的目录（我一个字节都没动过）

```
/workspace/team/runs/fpga_teammate/
├── HANDOFF_20261002.md                    ← 完整交接文档（含实例地址）
└── rtllm_pair_20261002T074340Z/           ← 你的那轮实验，原样
    ├── tasks_verified/                    44 题冻结题集（我原样复用）
    ├── taskset_manifest.json              题集清单与排除理由
    ├── paired_results.json                你的配对结果
    ├── RESULTS.md
    └── controls/                          你做的正例/反例对照
```

### 6.3 其它

| 内容 | 路径 |
|---|---|
| 完整交接文档（原件，含地址） | `/workspace/team/HANDOFF_20261002.md` |
| 官方 kit + 判定器 | `/workspace/team/tasks/autodl-rtl-kit/project/` |
| VerilogEval 156 题 | 上面 kit 的 `bench/tasks_veval/` |
| 模型 | `/workspace/team/models/Qwen3.6-27B-Q4_K_M.gguf` |
| 我历次实验 | `/workspace/team/runs/fpga_owner/` |
| 你的冻结题集（我用的） | `/workspace/team/runs/fpga_teammate/rtllm_pair_20261002T074340Z/tasks_verified/` |

---

## 7. 未提交到 GitHub 的改动

**`04_project/amd_rtl_agent/submission/agent/runtime.py` 有未提交改动**（就是 xelab 那段）。

- 本地：已改，**未 commit**
- 实例：**已还原**为原始版
- GitHub：原始版（`HEAD` 里没有 xelab）

**为什么没提交**：实验没跑完，结论可能是"该回滚"，提交了就会把未验证的东西记成既成事实。

**你要接手的话有两种选择**：
1. 让我把它提交到一个独立分支（如 `exp/xelab-check`），保留记录但不污染主线
2. 你自己在本地决定

**告诉我一声就行，或者你自己在本地 `git status` 就能看到。**

---

## 8. 环境硬约束（重复一遍，很重要）

1. **实例永远不要关闭**
2. 推理服务 PID `1198635`，`-np 1` **单槽**——**别并发跑评测**，会互相拖慢且污染结果
3. 不要改官方 `baseline.py` / `run_baseline.sh`（有 SHA-256 校验）
4. 长任务一律 `nohup`（SSH 会瞬断）
5. 实例**没有直连外网**，走平台代理（`HTTPS_PROXY` 在 `/proc/1/env` 里，交互式 `env` 看不到）
6. **一次只改一个变量**，且必须与基线配对比较
7. **单题差异不是结论**（本底噪声约 3.2%/题）

---

## 9. 如果你只做一件事

**做 4.2 的端口一致性审计。**

理由：它是唯一能**改变结论性质**的检查——如果 RTLLM 的描述和参考对不上，那"增益没迁移"就不是模型的锅，我们后面所有推论都要重来。而它只要 10 分钟。

**如果你做两件事**：再加 4.1 的提示 A/B（5 分钟）。

---

## 10. 有问题直接问

我是原会话的 Agent，本地项目在 `E:\26qiansai\`，通过 `HANDOFF_20261002.md` 和这份文档交接。

**我没有对你隐瞒任何东西。** 如果你发现这份文档里缺了什么、或者哪条对不上，那是我漏了，直接说。
