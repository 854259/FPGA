# RTL 官方接口适配交接（2026-09-21）

## 本轮结果

从队友最新 `60fca42` 派生，工作区 `E:/26qiansai/FPGA-official-contract`，
分支 `feat/official-rtl-contract`。旧工作区和历史112/156保持原样。
官方仓库固定到 `afd135e7ba5f6ec4c6d77e7c927c894327537801`。

- `04_project/amd_rtl_agent/submission/` 是独立正式入口：原版baseline及入口、
  题面输入、solution.v/trace.jsonl输出、带鉴权的健康检查和投题服务、
  同模型两模式、独立临时目录和限时子进程。
- 修复只使用自身候选的结构/编译错误。没有参考测试台、参考答案或外部评分反馈；
  暂未实现自建功能测试。编译通过不冒充功能通过或官方L1。
- `official_reference/` 保存原版评分、判定器、转换器、三道示例和规则文档，
  每文件哈希见UPSTREAM.json。这些只给外部评测器，不进入提交包。
- `official_eval.py` 使用官方判定器和汇总函数。检查完整题目/样本集合，
  L0/L1/L2/L3系数0/0.2/0.7/1，tool_error按官方逻辑排除，保留排除清单。
  样本不足5次明确标为非五样本协议；不把占位增益阈值换算成正式总分。
- 旧112/156为开发条件成绩，本轮未调用真实模型、未重跑全量、未产生正式分数。

## 队友下一步（Linux/WSL，Vivado 2026.1）

先在 `04_project/amd_rtl_agent` 运行自动测试：

```bash
python3 -B -m unittest discover -s tests -q
```

然后准备真实工具环境，先做不调用模型的官方reference自检：

```bash
source "$XILINX_VIVADO/settings64.sh"
export EDA_TMP=/tmp/eda
export SELFTEST_TMP=/tmp
mkdir -p "$EDA_TMP"
python3 official_eval.py --tasks official_reference/tasks \
  --out outputs/official_reference_check_new --reference --samples 1 --deadline 300
```

这里300秒是本次试跑预算，不是官方最终时间预算。官方Linux脚本需要可执行位，
仓库已登记；压缩包丢失权限时只对submission两个入口和
official_reference/selftest/judge两个脚本恢复执行权限。

reference自检确认后，启动本地兼容模型服务，按submission/README.md设置
同一LLM_BASE_URL与MODEL_NAME；先检查/v1/health。下列命令会调用真实模型，
仅在安排好计算后执行，先用三道示例，不直接跑156题：

```bash
python3 official_eval.py --tasks official_reference/tasks \
  --out outputs/official_examples_pair_new --samples 5 --deadline 300
```

每道题5次agent、5次官方baseline；一个实验目录内配对，保留全部逐样本判定。
进度/版本/输入哈希在experiment.json，分级报告在graded_summary.json。
不支持覆盖或续跑旧目录；中断保留complete=false，不生成伪完整成绩。

156题必须另用固定官方 `selftest/veval_import.py` 转换到新目录，并先reference
检查；不改旧数据，不把旧099/156异常直接套进新统计。官方自检仍是公开开发集，
不能当作最终隐藏题成绩。

## 已验证与未验证

本机Windows、Python标准库；测试使用本地假模型HTTP服务和固定编译返回，
验证真实子进程/HTTP协议，不用云API。包括200次连续投题（agent/baseline各100次）、
鉴权、超时恢复、候选编译修复反馈、禁止参考输入、原版脚本哈希与官方评分聚合。
具体测试数量和结果见bench/results/official_contract_20260921.json。

本机无WSL及Vivado2026.1，未执行真实官方判定、Linux信号回收、真实GPU/断网镜像。
本轮仅验证Windows进程取消；Linux使用独立进程组回收，仍需目标环境验证。
正式镜像标签、预算及增益阈值未发布，ROCm/量化权重/模型声明尚待部署阶段补齐。
健康检查不伪造显存，无amdgpu计数器时submission模式ready=false。
官方baseline不带API鉴权；云API需同一网关适配，不能修改原版基线。

## 版本与规则来源

- 官方RTL仓库：https://gitee.com/Vickyiii/rtlagent2026
- 文档定位：docs/FAQ.md Q8；docs/API_CONTRACT.md §2–5、§8–10；SCORING.md §2.12、§3。
- 用户提供的D:/QQwenjian/07_AMD_RTL本地智能体.md为本轮差异输入。
- 规则文档属于参考资料；本轮操作授权来自用户“好的你搞一下”。
