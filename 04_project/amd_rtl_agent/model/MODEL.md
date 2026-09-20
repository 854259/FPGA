# 模型声明

## 当前实际评测安排（2026-09-20 用户确认）

- 正式开发评测使用 Qwen3.6-27B，由队友机器承担推理及完整计算。
- 本机仅负责代码调试、mock 回归与少量串行 EDA 样例，不加载大型权重，不自动启动全量评测。
- 队友通过 `LLM_BASE_URL`、`LLM_MODEL`、`LLM_MODEL_REVISION`、`LLM_QUANTIZATION`
  声明实际服务、模型版本和量化；未知版本/显存保持未知，模型名称本身不是权重哈希证明。
- 下文 7B CPU 权重与镜像保留为历史接口验证资产，不是当前使用模型，也不能替代 27B 部署实测。

## 历史本地工程烟测

- 推理接口：OpenAI-compatible `POST /v1/chat/completions`。
- 推理后端：`llama.cpp` 的 `llama-server`；单元测试另有不联网的固定 mock。
- 本机阶段：CPU 路径，仅用于验证接口、基线约束、控制流和 EDA 闭环，不作为比赛性能结论。
- 上下文：8192 tokens。
- 单次输出上限：2048 tokens。
- 温度：0.2。
- baseline 与 agent 使用同一模型、服务、上下文、输出上限和温度。

## 已冻结的 CPU/后续 ROCm 候选权重

- 仓库：`Qwen/Qwen2.5-Coder-7B-Instruct-GGUF`。
- 许可证：Apache-2.0；官方许可证副本为 `model/LICENSE-Qwen2.5-Coder`。
- revision：`13fb94bfda8c8cf22497dc57b78f391a9acb426a`。
- 文件：`qwen2.5-coder-7b-instruct-q4_k_m.gguf`。
- 量化：Q4_K_M。
- 字节数：`4683073536`。
- SHA-256：`509287f78cb4d4cf6b3843734733b914b2c158e43e22a7f4bf5e963800894d3c`。
- 微调：无。

## 容器内 CPU 推理运行时

- 来源：本机从 llama.cpp commit `010be9683afabe14ce299197b38c329f94bae568` 编译的 Linux x86_64 CPU 产物。
- 位置：`runtime/llama/`；镜像内为 `/opt/llama/`，`serve.sh` 可直接启动。
- `llama-server` SHA-256：`f65a44b41f230a01afe70ab9021d65af4705fa1241664b14bae5ed7549b6a6d2`。
- 其他动态库 SHA-256 由 `runtime/llama/SHA256SUMS` 固定。
- llama.cpp MIT 许可证副本为 `runtime/llama/LICENSE-llama.cpp`。
- 该运行时只用于 CPU 复现；后续 ROCm 后端必须单独构建并实测。

## 尚未伪造的字段

- `measured_vram_gib`: `pending_official_rocm_measurement`
- `rocm_backend_build`: `pending_official_rocm_measurement`

赛事方 ROCm 单卡环境到位后，必须实际测量并替换上述字段；不得用估算值冒充实测值。
