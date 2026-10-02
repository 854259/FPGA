# 高危缺陷：`/v1/health` 恒报 `ready: false`（已修复并部署）

- 日期：2026-10-03
- 发现者：原会话 Agent（工程负责人）
- 性质：**两个独立缺陷，各自都足以让 `ready` 恒为 false**
- 状态：**已修复、已部署、已按真实 HTTP 契约验证**

---

## 1. 为什么这是高危

官方契约（`official_reference/docs/API_CONTRACT.md`）写着：

> ## 二、`GET /v1/health`
> **赛事方在投题前调用**，确认服务与模型就绪。
>
> | `ready` | 模型已加载、智能体可用时为 `true` |

**这是投题前的就绪门。** 我们实测：

```
{"ready": false, "track": "rtl", "model": "Qwen3.6-27B-Q4_K_M", "vram_gb": 67.446}
```

**两种 profile 下都是 `false`。** 若赛事方据此拒绝投题，后果是**全部样本拿不到分**。

**契约里还记录了一次真实事故**：HLS 服务因端口被占启动失败，而 RTL 服务仍在应答，
投题机照常投题，24 个 HLS 样本全部收到 Verilog，**表面看不出异常，直到判定才发现**。

**这说明赛事方确实读这些字段并据此行动。** `ready: false` 不是可以忽略的瑕疵。

## 2. 根因一：正则大小写

```python
match = re.search(r'Vivado\s+v?(\d{4}\.\d+)', result.stdout)   # 大写 V
```

而 `vivado -version` 的实际输出是：

```
vivado v2026.1 (64-bit)      # 小写 v
```

**`re.search` 默认区分大小写 → 永远匹配不上 → 返回 `None` → `ready` 为 false。**

（顺带排除：`vivado -version` 实测 **0.87 秒**，原来的 5 秒超时不是问题。）

**修复**：加 `re.I`，并把超时放宽到 30 秒（Vivado 在负载高时会慢很多）。

## 3. 根因二：显存把 8 块卡全加了

原实现：

```python
counters = list(Path('/sys/class/drm').glob('card[0-9]*/device/mem_info_vram_used'))
return round(sum(int(p.read_text().strip()) for p in counters) / 1024**3, 3)
```

**这台机器有 8 块独立 AMD GPU**（不同 PCI 槽），而且**有别的租户在用**：

| card | PCI | 显存占用 |
|---|---|---:|
| card1 | 0000:03:00.0 | 0.026 GB |
| card2 | 0000:23:00.0 | **29.059 GB** ← 别的租户 |
| card3 | 0000:43:00.0 | 19.295 GB |
| card4/5/7/8 | — | 各 0.026 GB |
| **card6** | **0000:a3:00.0** | **18.940 GB** ← **我们的模型** |

**求和 = 67.425 GB**，而 submission profile 要求 `<= 32` → `ready` 为 false。

**而我们的真实占用是 18.940 GB**——**与 `manifest.json` 里写的 `measured_vram_gb: 18.98` 完全吻合**。
**manifest 一直是对的，是 runtime 的实现错了。**

`llama-server` 持有 `/dev/dri/renderD133` → PCI `0000:a3:00.0` → card6，这就是归属依据。

**修复**：不求和，而是**归因到模型服务实际持有的那块卡**：
从 `LLM_BASE_URL` 取端口 → `/proc/net/tcp` 找监听 socket inode → 扫 `/proc/*/fd`
找到持有该 socket 的进程 → 读它打开的 `renderD*` → 映射到 card → 读该卡的计数器。
找不到时回退为"最忙的单卡"。

## 4. 验证

**按真实包布局**（`<stage>/agent/runtime.py` + `baseline.py` + `run_baseline.sh` + `upstream.json`）：

```
1) model in models() : True
2) baseline_integrity: True
3) vivado_tool(xvlog): found
4) vivado_version    : '2026.1'     ← 修复前是 None
5) vram_gb()         : 18.94 GB     ← 修复前是 67.425

RTL_PROFILE=development -> {ready: True, ...}
RTL_PROFILE=submission  -> {ready: True, ...}
```

**按真实 HTTP 契约**（部署后）：

```
GET  /v1/health → {"ready": true, "track": "rtl", "model": "Qwen3.6-27B-Q4_K_M", "vram_gb": 18.94}
无 token        → HTTP 401
POST /v1/solve  → HTTP 200，74 字符，2.118s
```

**两个 profile 都 `ready: true`，`track` 为 `rtl`，`vram_gb` 为真实值。**

## 5. 部署

| 项 | 值 |
|---|---|
| 旧 runtime | `22e32251664f31a6`（已备份） |
| 新 runtime | `cea6479c6364fbfc` |
| 备份 | `/workspace/team/runs/fpga_owner/runtime_backup_20261003/runtime.before_22e32251664f31a6_readyfix.py` |
| 测试套件 | **82 个全过** |

## 6. 这个缺陷暴露的流程问题

**我们的全部自检——312 个样本、两轮全量、逐题判定——都没有碰过 `/v1/health`。**

原因是我们一直用 CLI（`official_eval.py` 走 `runtime.py run`），**而赛事方走 HTTP**。
**CLI 路径不经过 `health()`，所以这个缺陷在我们的所有测试里都是隐形的。**

**新纪律：契约里定义了哪些接口，就要对哪些接口做端到端验证，不能只测自己习惯的入口。**

这与本轮早些时候的 `pkill` 教训同源：**验证的是自己走的路径，而不是对方会走的路径。**

## 7. 尚未做

1. **5 样本协议仍只验证了 1 道题 × 5 次**（`Prob001_zero`，5 次完全一致）。全量 1560 次未跑。
2. 修复后**未重跑全量配对**——但该改动只影响 `health()` 与 `vram_gb()`，
   不进入 `run` / `worker` 路径，**理论上不影响任何分级**。严格来说仍需一次全量确认。

## 8. 证据位置

| 内容 | 路径 |
|---|---|
| 契约原文 | `04_project/amd_rtl_agent/official_reference/docs/API_CONTRACT.md` |
| 修复后的 runtime | `04_project/amd_rtl_agent/submission/agent/runtime.py`（`cea6479c6364fbfc`） |
| 诊断与验证脚本 | `/tmp/diag_ready.sh`、`/tmp/diag_ready2.sh`、`/tmp/diag_which_gpu.sh`、`/tmp/verify_ready2.sh` |
| 部署脚本 | `/workspace/team/deploy_readyfix.sh` |
| 5 样本探测 | `/workspace/team/runs/fpga_owner/five_sample_probe_20261003/` |
