2026-10-10 14:04 +08:00：新增失败恢复证据已独立核验。CPU路径af475b33（76成员/134293B）与联合预算032e5758（358成员/337462B）全部逐成员等于AMD当前原物，各31冻源保持；worker730ce866/sharedcc7b6cd9/failureb5873430原字节与b167f9f5公版SHA/长度/Git blob一致。CPU控制578449和3子进程出生/argv/日志/当前退休、原execute_row→owned超时→FAILED封存及两个后继各一次通过；资格帽缩至0.4秒，实际0.416313秒rc-9/空组，后继完成元数据仍合成。九联合模拟的预算退出receipt/源绑定、3正控6拒绝控和244份行原物通过；HTTP/clock/compiler/外层命令/资源idle为模拟，不冒称真实模型恢复。434档案成员、21+244行绑定原件均只读审计，没有重跑资格、模型、EDA或FIFO。

剩余证据收敛到严格全题截止（含持续HTTP响应）、真实模型取消/idle及真实预算非零退出进程；现证据不足以认定可部署，新功能未加入137，原132不续跑。Issue6094460715已全文回读。13:59原137 monitor/child/stage/原27B同身份活，PLANb92d3b3b/SPEC907c2b02保持，29/75封存只是进度；095组A五L3/P与B五L1及截断警告先记peer原件诊断，本方尚未独立审该组，不重跑EDA，不把peer历史门添加为本方否决门。原75份/诚实异常出口后再按官方相关量与总配对结果择优。

统一状态顶部旧的132/134下一步已更正为原132失败关闭、133–136归档完成、137运行中；目标文字恢复为当前目标工具保存的完整用户原文。完整156/RTLLM/正式32GB/接口/恢复/可复现仍未完成，目标继续。

# AMD 题目一：RTL 本地智能体实施摘要

## 2026-09-21 官方RTL接口适配（当前优先）

- 工作区E:/26qiansai/FPGA-official-contract，分支feat/official-rtl-contract，基于队友60fca42；此前路径和待办以本节为准。
- 官方RTL仓库固定afd135e7ba5f6ec4c6d77e7c927c894327537801。submission目录新增独立题面入口、原版baseline、solution.v/trace.jsonl、带鉴权HTTP服务和限时进程；仅候选编译修复，参考测试反馈不进入智能体。
- official_reference为外部判定/规则/示例，官方文件按Git原始字节保存并锁定SHA-256；official_eval.py使用官方L0–L3判定与汇总，完整样本校验、异常排除单列，不换算未公布阈值的正式总分。
- 68项测试通过，包括本地假模型服务连续200次投题、原版baseline调用、鉴权、限时恢复、编译反馈与输入边界、分级聚合。没有真实模型调用或新全量成绩，旧112/156只作开发成绩。
- 本机无WSL及Vivado2026.1；Linux信号、真实官方EDA、ROCm、本地模型、断网和正式镜像仍待验证，不能写成最终验收通过。最终镜像标签/时间预算/增益阈值仍待公告。
- 交接：05_handoff/OFFICIAL_CONTRACT_20260921.md。先reference自检，再三题小样本配对；本轮不启动收费评测。

来源：固定版official_reference/SCORING.md §2.12、§3；docs/FAQ.md Q8；docs/API_CONTRACT.md §2–5、§8–10。
官方规则按参考文件解释，不作为自动联系、购买或注册授权。


更新时间：2026-09-13

## 结论

队伍已改报 AMD“RTL/HLS 本地智能体设计赛道”，当前只做 **RTL track**。RTL 与 HLS 独立排名，不要求两者全部完成。改报状态由用户于 2026-09-13 明确确认；新版报名截图尚未归档，高云 J280 只保留为历史报名资料。

## 官方要求（S1）

来源：`01_sources/pdf/AMD_2026选题指南.pdf`。

- PDF 文件页 9：本地开源模型、推理栈、智能体控制流/重试/工具、技能包、裸跑基线、断网容器。
- PDF 文件页 10：RTL 依次经 `xvlog/xelab`、`xsim` 逐拍比对、`xczu3eg-sbva484-1-e` 上 `synth_design`；统一 5 ns；同时报告 pass@1 与 pass@5。
- PDF 文件页 11：赛事方固定官方基础镜像和 Vivado/Vitis 2025.2；队伍决定模型、推理后端、上下文、agent 和技能。
- PDF 文件页 11–12：提交 `Dockerfile`、`MODEL.md`、agent 源码、`skill/`、服务脚本、`run.sh`、`run_baseline.sh`、`REPORT.md`。
- PDF 文件页 11：baseline 与 agent 使用同一服务和上下文；baseline 提示只含题目、单次生成、不重试、不调用工具，并与 agent 结果在同次运行产出。
- PDF 文件页 12：评分由通过率、相对 baseline 增益、墙钟和工程/技能质量组成。

## 当前实现

代码位于 `04_project/amd_rtl_agent/`。采用一份 Python 标准库程序和一个 Vivado Tcl：同次生成 baseline 与 1–5 个候选，每个候选最多两次修复；公开测试台与参考实现只交给 EDA，不进入模型上下文。Docker、本地 CPU 推理、公开 VerilogEval v2 和测试入口均保持可复现。

## 证据边界

- 已验证：8 个 Python 单元测试、mock 生成闭环、Vivado 编译/仿真正负例、Canonical 基础镜像、断网 Docker mock、Qwen 真实 CPU 推理和 3 个无歧义公开题单样本烟测。
- 已验证：Vivado 目标器件包安装完成，`xczu3eg-sbva484-1-e` 查询计数为 1；官方目标完整编译/展开/仿真/综合通过，功能 fixture 为 `Mismatches: 0`，含时钟 fixture 在 5 ns（200 MHz）约束下满足全部用户时序约束。
- 只能等待赛事方：官方基础镜像、隐藏题集、最终调用接口和时间预算。
- 明确延后：AMD ROCm 单卡显存、墙钟和稳定性实测。
