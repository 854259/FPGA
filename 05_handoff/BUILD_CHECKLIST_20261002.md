# 官方基础镜像到位后的构建与验证清单

- 建立时间：2026-10-02
- 当前状态：**官方基础镜像尚未公布**，`submission/Dockerfile` 里的 `BASE_IMAGE` 是占位符
- 依据：`hlsagent2026/example/Dockerfile`（Gitee `Vickyiii/hlsagent2026` @ `2c242fd7`，2026-09-21）与接口契约
- 本地存档：`04_project/amd_rtl_agent/official_reference/upstream-20261002/`

## 0. 为什么这条最重要

评分细则 **2.1**：方案须基于官方基础镜像构建、可独立重建、且能由赛事方在自有环境复现运行。
**未满足的后果是「全部运行类得分无法产生」**——这是目前唯一还会导致整体归零的未决项。

而且官方明确：**即使队伍自备 ROCm 环境，仍必须提交可在赛事方环境中重建的容器与脚本。**

## 1. 需要等到的输入

| 输入 | 来源 | 状态 |
|---|---|---|
| 基础镜像正式名字与标签 | 赛事方，**验证窗口前公布** | ⏳ 未公布 |
| 目标变体选择：`gfx1100`（验证窗口，W7900）或 `gfx1201`（决赛，R9700） | 依据实际评测阶段选定 | ⏳ |
| 验证窗口与评测窗口时间点 | 「另行公告」 | ⏳ |
| 云资源配额与申请方式 | AMD 中国开发者平台 | ⏳ |

占位符形式（来自官方范例）：`fpgachina2026/base-gfx1100:REPLACE_WITH_ANNOUNCED_TAG`

## 2. 构建

```bash
cd 04_project/amd_rtl_agent/submission
docker build --build-arg BASE_IMAGE=<公布的名字> -t 45561-agent .
```

若还需要把权重烤进镜像，在构建前放开 `Dockerfile` 里 `COPY models/ /opt/models/` 两行，
并把量化权重放到 `submission/models/`。

## 3. 构建后的验证（逐条记录实际输出，不得凭推断）

| # | 检查 | 通过判据 |
|---|---|---|
| 1 | `docker run --rm 45561-agent python3 -c "import sys;print(sys.version)"` | 打印版本，无报错 |
| 2 | 容器内 `echo $XILINX_VIVADO` | 非空；**不要**在 Dockerfile 里自己设 |
| 3 | 容器内 `vivado -version` | 含 `2026.1` |
| 4 | 容器内 `xvlog -version` / `xelab -version` / `xsim -version` | 均可执行 |
| 5 | 目标器件 `xczu3eg-sbva484-1-e` 可综合 | `synth_design` 产出网表且无 ERROR |
| 6 | 权重在位：`ls -l $MODEL_PATH` | 大小 `19,095,766,304`、SHA-256 `65b753ea…` |
| 7 | 断网启动服务：`docker run --network none … ./serve/llama.sh` | `/health` 返回成功，最短请求不含 `<think>` |
| 8 | 单题跑通：容器内 `./run.sh <task> <out>` | 产出 `solution.v` 与 `trace.jsonl` |
| 9 | 基线跑通：`./run_baseline.sh <task> <out>` | 同上，且 `upstream.json` 哈希校验通过 |
| 10 | 参考自检：`official_eval.py --reference` | 3/3 L3，零工具错误 |
| 11 | 端到端冒烟：`official_eval.py`（无 `--reference`） | agent 与 baseline 各 3 题，零工具错误 |
| 12 | 单卡显存 | **在最终目标卡上**实测 ≤ 32 GB（现有 19.0 GiB 是开发卡 gfx1100 的采样） |

失败时保留完整日志作为排障证据，不把失败结果改写成通过。

## 4. 已知的构建陷阱（来自官方范例与我们的实测）

| 陷阱 | 说明 |
|---|---|
| 启动时下载权重 | 沙箱断网，`huggingface-cli download` 会失败。权重必须构建期拷入或运行期挂载 |
| 自己设 `PATH` / `XILINX_*` | 基础镜像已导出；工具布局在 2026.1 是「版本在前」、2024.2 及更早是「工具在前」，硬编码路径会跨版本失效 |
| 设了 `ENTRYPOINT` | 赛事方直接调 `run.sh` / `run_baseline.sh`，容器不要抢占入口 |
| 暴露推理端口 | 只暴露提交口（7860）；两个服务都只绑 `127.0.0.1`，由平台隧道转发 |
| 绑 `0.0.0.0` | 服务活着但外面打不进来，而失败不重投——看起来和挂掉一样 |
| 思考未关闭 | Qwen 系模板默认输出 `<think>`，会吃掉输出预算导致截断；实测截断率 37.1% → 1.8% |

## 5. 完成后要更新的文件

- `PROJECT_STATE.json`：新增 `official_base_image_*` 记录（镜像名、digest、构建时间、验证结果）
- `05_handoff/CHANGELOG.md`：记录构建与验证结论
- `model/MODEL.md`：把 `final_image_vram_measurement` 从「待实测」换成最终卡实测值
- `REPORT.md` 第 9 节：把「官方基础镜像未发布」改为已构建并验证的事实
