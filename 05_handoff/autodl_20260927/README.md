# 明天从这里开始：AutoDL 5090 准备包

准备日期：2026-09-26，计划使用日期：2026-09-27。
仓库位置：`05_handoff/autodl_20260927/`。原电脑的独立准备目录为 `E:\26qiansai\AutoDL-20260927`；队友可直接使用当前仓库目录。

队友先下载本目录的 `autodl-rtl-kit.tar.gz` 和同名 `.sha256` 校验文件，按下面 A–F 执行。无需先重建部署包。包内已含固定源码和 156 题。

需要重建时，在完整克隆的仓库中运行 `python build_bundle.py`，它从固定历史提交读取源码，不要求当前 HEAD 回退；随后运行 `python verify_bundle.py`。重建需要网络下载固定数据集，shell 语法检查需要 Bash。`kit/` 中的文件是准备脚本模板，评测项目和数据在压缩包内。

## 已准备

- Windows 自带 SSH/SCP 可用，VS Code Remote SSH 插件已安装。
- 源码固定 a53e343ed9f02434050fdf86e61bae1b4a0c11a7，与检查时远端 feat/official-rtl-contract 一致。
- 原项目 68 项本地测试通过；日志在 logs/local-tests.txt。这些包含模拟模型，不代表 GPU/EDA 已验收。
- 156 组公开题面、参考答案、测试台已下载并按固定官方转换器转换。
- 上游 baseline、判定器和规则的原始字节哈希已核对。
- 上传包 autodl-rtl-kit.tar.gz 不含账号密码、密钥、模型权重或 Vivado；也不包含历史实验输出。

## 明天仍必须解决

1. 你在 AutoDL 登录、选择并启动一张 RTX 5090 32GB 实例。
2. 云端安装/提供 Vivado 2026.1 Linux、目标器件 xczu3eg-sbva484-1-e 和实际可用的许可。已有 Windows 2025.2 不能替代这一步。
3. 选定兼容的 NVIDIA 驱动、vLLM 与量化模型组合，并完成真实请求。

候选权重 nvidia/Qwen3.6-27B-NVFP4 的 revision 记录在 kit/model-lock.json。它尚未在本机 GPU 验证，不保证 AutoDL 默认镜像开箱可用。当前 vLLM 配方对这一候选的 SM120 路径要求 >=0.28；不能在旧 vLLM 镜像上直接照抄启动。不要把此前 API 模型成绩当作本地量化成绩。

## A. Windows：连接和上传

租卡后，AutoDL 给出的指令类似 ssh -p 12345 root@某个主机。只提取其中的主机和端口，以下 HOST、PORT 必须替换。密码在 SSH 交互提示中输入，不要写进脚本或聊天。

在此目录打开 PowerShell：

```powershell
.\connect.ps1 -Server HOST -Port PORT -Action Upload
.\connect.ps1 -Server HOST -Port PORT -Action Connect
```

若执行策略阻止脚本，可直接使用现有系统命令，不必修改执行策略：

```powershell
scp -P PORT .\autodl-rtl-kit.tar.gz .\autodl-rtl-kit.tar.gz.sha256 root@HOST:/root/autodl-tmp/
ssh -p PORT root@HOST
```

SSH 第一次询问主机指纹时，核对所连接主机来自自己的控制台，不要关闭主机密钥检查。

## B. 云端：解包

以下均在云端 Linux 终端执行。先确认数据盘的实际位置确为 /root/autodl-tmp。

```bash
cd /root/autodl-tmp
sha256sum -c autodl-rtl-kit.tar.gz.sha256
mkdir rtl-session-20260927
tar -xzf autodl-rtl-kit.tar.gz -C rtl-session-20260927
cd rtl-session-20260927/autodl-rtl-kit
python3 -B check.py
cp env.example.sh env.local.sh
```

编辑 env.local.sh：填写真实 Vivado 和模型路径。不要重用已有 rtl-session-20260927 目录；再次尝试请另取日期/后缀。

此包包含外部评测用的参考答案。它是开发工具包，不是最终提交包；最终提交的源代码边界是 project/submission/，正式隔离需要额外处理。

## C. 模型权重与启动

权重应在云端数据盘直接下载，避免先下载到 Windows 再上传几十 GB。先激活已选定且支持 5090/该权重的 vLLM 环境，并安装其匹配的 Hugging Face 下载客户端。此包不会自动混装 CUDA/PyTorch。

有 huggingface_hub 后，按锁定 revision 下载：

```bash
source ./env.local.sh
python3 - <<'PY'
import json, os
from huggingface_hub import snapshot_download
lock = json.load(open('model-lock.json'))
snapshot_download(repo_id=lock['repository'], revision=lock['revision'], local_dir=os.environ['MODEL_PATH'])
PY
```

先检查 MODEL_PATH 不包含 CHANGE_ME。使用 tmux 保持会话（若镜像未装 tmux，先安装平台支持的软件包）：

```bash
tmux new -s rtl-model
bash start_model.sh
```

Ctrl+B 后按 D 离开会话，模型继续运行。另一个终端加载环境并做三次真实请求：

```bash
source ./env.local.sh
python3 -B smoke_model.py
```

start_model.sh 是根据候选模型配方准备的保守启动模板，已做语法检查，尚未实测 GPU。默认单并发、16K 上下文、85% 显存预算、同一聊天模板；启动失败先查日志，不应通过随意修改 baseline 解决。

## D. Vivado 与正式判定入口

安装/准备好 Vivado 2026.1 后，在当前 shell：

```bash
source ./load_env.sh
python3 -B check.py --host
python3 -B -m unittest discover -s project/tests -q
```

check.py --host 检查工具版本、模型列表、GPU 状态，但不能代替真实综合和许可自检。正式模式检查 AMD 显存；此处明确使用 RTL_PROFILE=development。

开始每个阶段前确认上一阶段日志和判定正常。每个命令自动建立独立输出目录：

```bash
python3 -B run_stage.py reference3
python3 -B run_stage.py smoke3
python3 -B run_stage.py pair3x5
python3 -B run_stage.py reference156
```

先核对 reference156 的环境/数据异常，保留排除清单，再运行全量：

```bash
tmux new -s rtl-eval
source ./load_env.sh
python3 -B run_stage.py full156
```

所有阶段默认 deadline=300 秒，这是本轮试验预算，不是官方最终限时。旧 baseline 内部仍有 300 秒请求超时；不要误以为增大外层 deadline 会自动调整它。

full156 是 156 题 × baseline/agent 各一次，agent 最多一次修复，不是 pass@5。每次输出目录不覆盖，当前官方评测器不支持断点续跑。日志在 logs/，逐题产物在 project/outputs/。运行期间可从另一个终端查看打印出的日志路径。

开始模型和评测前，可在另一个终端记录显存：

```bash
nvidia-smi --query-gpu=timestamp,name,memory.used,utilization.gpu --format=csv -l 5 > logs/gpu-monitor.csv
```

完成后 Ctrl+C 停止该监控。相同文件再次运行会覆盖，请换名。

## E. HTTP 接口单独检查

在同一个已加载环境的终端生成临时本机服务 token，不写入文件：

```bash
export FPGACHINA_TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
python3 -B project/submission/runtime.py serve --port 7860 > logs/http-service.log 2>&1 &
curl -f http://127.0.0.1:7860/v1/health -H "Authorization: Bearer $FPGACHINA_TOKEN"
curl -f http://127.0.0.1:7860/v1/solve \
  -H "Authorization: Bearer $FPGACHINA_TOKEN" -H 'Content-Type: application/json' \
  -d '{"task_id":"and_smoke","nonce":"20260927","mode":"agent","prompt":"Implement module TopModule(input a, input b, output y); with y equal to a AND b.","interface":"","deadline_s":300}' \
  > logs/http-solve.json
```

检查 ready=true、非空 solution 和 trace。这里不是官方 L3 判定。端口保持 127.0.0.1，无须公网暴露。

## F. 备份后关机

云端生成结果包（在 kit 目录，文件名加时间）：

```bash
tar -czf ../rtl-results-$(date +%Y%m%d_%H%M%S).tar.gz logs project/outputs source-lock.json model-lock.json
```

Windows 用实际结果文件名下载：

```powershell
scp -P PORT root@HOST:/root/autodl-tmp/rtl-session-20260927/rtl-results-实际时间.tar.gz .\
```

检查 experiment.json 的 complete=true、结果文件完整、异常排除已说明，再在 AutoDL 控制台关机。关闭 Windows 或 SSH 不会停止云端计费。

## 两人协作

你管理计费和开关机；队友用实例 SSH 连接。只运行一份模型服务，一个人启动全量实验；分别查看日志即可。不要共享 AutoDL 主账号密码。tmux attach -r -t rtl-eval 可只读查看队友的评测会话。

## 来源

- https://www.autodl.com/docs/ssh/
- https://www.autodl.com/docs/scp/
- https://huggingface.co/nvidia/Qwen3.6-27B-NVFP4
- https://recipes.vllm.ai/Qwen/Qwen3.6-27B
- 固定官方接口与判定器：project/official_reference/UPSTREAM.json
