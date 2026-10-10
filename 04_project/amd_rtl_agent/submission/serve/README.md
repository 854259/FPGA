# 推理服务

本目录是提交方案包中的 `serve/`，负责启动本地推理服务。方案（agent）与基线（baseline）**共用同一个服务实例**，这是评分细则的要求：两者必须出自同一次运行、同一个服务、同一份配置。

## 启动

启动完整服务守护器时，`bash /path/to/package/serve/serve_all.sh` 默认使用
同一提交包的 `agent/runtime.py`，不依赖调用者的工作目录。显式设置 `KIT`
仍表示旧项目根目录，入口为 `$KIT/submission/agent/runtime.py`；入口不存在时，
守护器在探测或启动模型/HTTP 服务前退出。模型、工具链和日志位置仍须按部署环境配置。
当前 HTTP/CLI 源码已接入所选候选，十一项 AMD CPU 链路/守护测试与两项专项 health 测试通过；模型/EDA 使用合成夹具，尚未部署为真实模型验证过的服务。守护器整体、正式镜像、32GB 和恢复验收仍待。HTTP 为主线程串行服务，solve 期间 health 会等待。守护器仅在记录的 agent 已退出后尝试启动；存活但 health 超时只告警，不中断当前 solve。三项真实 CPU 信号案例确认请求取消在清理后退出 HTTP 服务，即使传输包装或恢复失败也不继续接单。实际模型恢复仍待。

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
