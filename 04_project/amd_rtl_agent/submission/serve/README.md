# 推理服务

本目录是提交方案包中的 `serve/`，负责启动本地推理服务。方案（agent）与基线（baseline）**共用同一个服务实例**，这是评分细则的要求：两者必须出自同一次运行、同一个服务、同一份配置。

## 启动

启动完整服务守护器时，`bash /path/to/package/serve/serve_all.sh` 默认使用
同一提交包的 `agent/runtime.py`，不依赖调用者的工作目录。显式设置 `KIT`
仍表示旧项目根目录，入口为 `$KIT/submission/agent/runtime.py`；入口不存在时，
守护器在探测或启动模型/HTTP 服务前退出。模型、工具链和日志位置仍须按部署环境配置。
当前 HTTP/CLI 源码已接入所选候选；完整运行时身份以 `manifest.json` 的 `runtime.sha256` 为准。最近一次运行时代码验证对象是 PR267 的 `runtimeef1b1e04`，共享预算仍为 `c6aebf9f`；真实模型/EDA、完整服务、正式镜像、32GB 全生命周期及恢复资格仍待。历史十一项链路控制、两项 health 控制及后续十四项取消传播控制各自保留原版本范围，不将它们视为当前版本的整体验收。

HTTP 为主线程串行服务，solve 期间 health 会等待。当前 `serve_all.sh`（`0769680e`，PR261）只在首次启动流程启动服务，之后对模型和 agent 的无响应、存活或退出均只观测/告警，不自动停止、重启或重投。旧版“agent 已退出后可重启”的行为已废止。四种 model/agent × alive/exited CPU 控制通过；首次启动和真实服务连续性未由这些控制覆盖。

HTTP 从 `do_POST` 入口继承请求时钟，工作、清理和响应预留共用 `deadline_s` 总预算（PR262）。PR267 进一步将响应头和响应体的 socket 写超时限制在该绝对截止内；截止已过时关闭连接，不发送成功响应，部分响应写失败后不再追加第二条 HTTP 响应。七项受影响 HTTP 方法通过 AMD CPU 控制，另以原 2 MiB 慢读场景确认后续请求可继续；这是合成上游/响应夹具，不是真实模型恢复或正式外部墙钟验收。更早的排队/头部读取、JSON 序列化 CPU 时间和网络交付仍有未证明范围，不能承诺严格实时上限。旧四项 HTTP/solve、native 上限/默认 CLI 及信号控制保留各自源版本范围。

```bash
MODEL_PATH=/opt/models/Qwen3.6-27B-Q4_K_M.gguf ./serve/llama.sh
```

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `MODEL_PATH` | `/opt/models/Qwen3.6-27B-Q4_K_M.gguf` | 量化权重路径（必填） |
| `LLAMA_BIN` | `/opt/llama/llama-server` | llama.cpp 服务端可执行文件 |
| `MODEL_ALIAS` | `Qwen3.6-27B-Q4_K_M` | `/v1/models` 暴露的名称，运行端 `MODEL_NAME` 必须一致 |
| `MODEL_PORT` | `8000` | 服务端口 |
| `MODEL_CTX` | `16384` | 上下文长度 |
| `MODEL_NGL` | `99` | 卸载到 GPU 的层数 |
| `MODEL_THREADS` | `8` | CPU 线程数 |

模型权重、来源、版本、量化与显存实测见 [`../model/MODEL.md`](../model/MODEL.md)。

## 两个必须保持的参数

**1. 只绑 `127.0.0.1`。** 赛事平台的隧道只接管回环地址上的 HTTP；绑 `0.0.0.0` 时服务本身是活的，但外部永远打不进来，而失败不重投。

**2. 必须带 `--reasoning off`。** Qwen 系模板在 `enable_thinking` 未显式为 false 时会输出 `<think>` 块：

```jinja
{%- if enable_thinking is defined and enable_thinking is false %}
    {{- '<think>\n\n</think>\n\n' }}
{%- else %}
    {{- '<think>\n' }}
{%- endif %}
```

运行端（`agent/runtime.py`）不发送 `enable_thinking`，思考开关**完全由服务端这个参数决定**。若失效，每轮生成会先耗掉大段思考 token，导致 RTL 被截断——这会被误读成模型能力差。本队在 2026-09-27 的实验中实测到过 37.1% 的截断率，关闭思考后降到 1.8%。

启动后建议先做一次响应冒烟，确认返回内容不含 `<think>`。

## 端口

`serve/` 的模型端口（默认 8000）**只供容器内部调用，不对外暴露**。对外只需要 `agent/runtime.py serve` 的 HTTP 入口（默认 7860）；`run.sh` 是目录输入/输出的 CLI。

版本探测使用原生进程监督和脱离子进程回收，取消后退出服务；缓存命中不会重复启动版本工具。两项专项案例使用合成 CPU 工具，不代表真实 Vivado、模型或整个守护器已验收。
