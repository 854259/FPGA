# 变更记录

## 2026-09-21 官方RTL接口适配（当前优先）

- 已按用户要求发布并核验：官方适配代码075de5f4bdc797e82b43121d9097be6878fa073c已推送origin/feat/official-rtl-contract，远端SHA一致；main与队友原分支未改动。本次只同步发布状态，没有修改运行代码或重跑评测。

- 工作区E:/26qiansai/FPGA-official-contract，分支feat/official-rtl-contract，基于队友60fca42；此前路径和待办以本节为准。
- 官方RTL仓库固定afd135e7ba5f6ec4c6d77e7c927c894327537801。submission目录新增独立题面入口、原版baseline、solution.v/trace.jsonl、带鉴权HTTP服务和限时进程；仅候选编译修复，参考测试反馈不进入智能体。
- official_reference为外部判定/规则/示例，官方文件按Git原始字节保存并锁定SHA-256；official_eval.py使用官方L0–L3判定与汇总，完整样本校验、异常排除单列，不换算未公布阈值的正式总分。
- 68项测试通过，包括本地假模型服务连续200次投题、原版baseline调用、鉴权、限时恢复、编译反馈与输入边界、分级聚合。没有真实模型调用或新全量成绩，旧112/156只作开发成绩。
- 本机无WSL及Vivado2026.1；Linux信号、真实官方EDA、ROCm、本地模型、断网和正式镜像仍待验证，不能写成最终验收通过。最终镜像标签/时间预算/增益阈值仍待公告。
- 交接：05_handoff/OFFICIAL_CONTRACT_20260921.md。先reference自检，再三题小样本配对；本轮不启动收费评测。


## 2026-09-21 提示与反馈优化（本机验证完成，清理阻塞）

更新时间：2026-09-21T14:09:12+08:00。适用范围：当前D盘业务代码；连接恢复段由原任务维护。

- **已完成并验证**：候选绝对路径匹配的VRFC位宽/截断警告进入后续失败反馈（警告≤1024、合并诊断≤4096字符）；初始化按题面明确要求处理；输出禁止推导注释。baseline提示、模型预算和修复次数未改变。
- **已完成并验证**：保存返回model、finish_reason及三项token计数白名单；agent逐轮保存response_metadata.json，baseline纳入结果。格式失败且finish_reason=length时标记长度限制；重复诊断复用不携带上一响应的截断标签。未知/缺失字段不推断。
- **验证证据**：61项离线自动测试通过；真实Vivado2026.1两个场景4项断言通过，警告反馈修复候选和常量初始化用例均完成仿真及综合。使用固定mock响应、无API调用，不代表27B收益或200MHz时序达标。复用此前无关EDA负例验证，没有重复跑全量预检。归档134/137/139警告提取核对通过。
- **数据边界**：离线归档已核实099接口不匹配、156参考自比TIMEOUT；保留原始112/156、原始数据和输入哈希。未重跑这两项参考自检，不把审计内容送入模型。
- **成果路径**：04_project/amd_rtl_agent/bench/results/prompt_feedback_20260921.json；原始证据outputs/prompt_feedback_20260921；复现命令见README顶部和tests/run_vivado_regression.py --prompt-feedback-only。
- **已实现、效果待验证**：27B首次/修复后通过率、输出截断和源码重复比例、实际耗时。最小同配置旧新对照选6道退化题050/095/101/130/134/136，加初始化074、警告137/139、格式070/147及原已通过001/030/054，共14题。沿用Qwen3.6-27B、同工具/数据/seed1/temperature0.2/max_tokens2048、1样本1修复和thinking关闭；按原全量题序保持逐题seed映射，每版新目录。它是定向诊断，不能外推全量收益；通过后再授权156题。需真实模型才可继续判断效果，本轮停在此处。
- **发布状态**：实现提交5eb9711bb134638f0a107731b6224ab0a17725ca已推送fix/reliable-evaluation并经ls-remote核验；后续文档提交同步此事实。既有未提交资料与原件保留，本机旧10/156仍暂停。
- **收尾阻塞**：自动审批拒绝限定本轮目录的PowerShell清理（blocked by policy，无额外原因），没有删除或绕过。残留5个.Xil/xsim.dir目录及9个顶层.pb/.jou；明细在精简证据cleanup。32个有效证据文件哈希复核一致。实现和验证完成，任务清理未完成，不能宣告全部收尾。

## 2026-09-20 修复反馈与退步回退

- 实现提交21223b2ebf840e57b836add7a70efe99a38d4c02已推送fix/reliable-evaluation并通过ls-remote核验；main仍为d5753b4。后续文档提交只记录此发布事实。
- 按用户“现在有什么能改动优化”请求，使用离线固定输入复现三项问题，再先补失败测试并修改现有agent.py，没有引入新架构或依赖。
- 输入方向正则原先会跨逗号误认output，还会命中注释、其他模块和范围表达式；现在限定TopModule简单ANSI端口，复杂声明不作确定性方向判断。
- 原逻辑仅在最终输出保留最佳代码，下一次修复仍接着退步版本；现在出现较差阶段/较高归一化错误率时，把较好代码及其对应反馈一并交给下一轮。质量相同继续新候选，新增repair_from_attempt记录来源。
- 日志筛选保留诊断后两行内带Time/File/Scope/Process/Iteration前缀的上下文；没有从总错误数虚构波形，保留4096字符上限。
- 57项自动测试通过；新增--repair-backtrack-only入口，以固定响应驱动真实Vivado2026.1编译和仿真：首版Mismatches: 2，第二版语法错误，第三轮回到首版修改并Mismatches: 0。5个流程断言通过，原始证据outputs/repair_feedback_20260920_234100，精简证据bench/results/repair_feedback_20260920.json。
- 本轮没有真实模型、全量、GPU或综合实测；不把mock调用记成27B能力提升。初始生成skill/baseline/模型预算不变；回退需要仍有修复机会，一次修复配置不自动加次数。
- 已重审新输出目录，工具进程已结束。新目录3个xsim.dir及.pb/.jou清理命令被自动审批以blocked by policy拒绝，没有给出其他理由；未删除或绕过。既有资料改动、历史输出、暂停10/156批次与stash保持。

## 2026-09-20 可靠性优化与27B队友交接

- 优化代码提交b9fd7b50609510a99137d89ca65cf70b70d35173已推送origin/fix/reliable-evaluation，使用git ls-remote核验一致；main未修改。此后的文档提交用于记录已验证发布状态。

- 用户明确本机只调试代码，队友用27B运行完整计算；同步当前模型/工作分工，7B保留为历史烟测。
- 旧全量启动器缩减为统一benchmark入口，强制指定目录与显式续跑，沿用环境配置，不再自动混合旧progress记录或重试收费请求。
- 识别工具/许可证/器件缺失后保存日志、中断评分并留下当前题error.json；保护单题、baseline及EDA日志，综合要求完成标志与非空产物。
- 保留样本评测质量用于跨样本选择；续跑核对EDA日志、报告、DCP和PASS，文件哈希采用分块读取；时序字段明确记录约束，timing_pass为null。
- 超时/普通中断尝试回收进程树或进程组。负例要求实际RTL诊断，修复回归补上综合；本机环境检查默认不启动本地模型或Docker。
- 52项自动测试通过，5项Vivado2026.1真实EDA回归通过；Windows超时子进程回收有真实小进程验证，普通中断有mock回归，POSIX分支未运行。EDA回归后补充的中断清理通过单测，未重复正常综合流程。
- 可移植证据bench/results/reliability_20260920.json；原始证据outputs/reliability_20260920_220835。本轮没有加载/调用模型、没有全量评测或GPU测试；新版27B成绩、显存和耗时由队友实测。
- 已重审本轮输出，确认无本次EDA残留进程。清理该次运行9个.Xil/xsim.dir缓存目录的原生PowerShell命令被自动审批以blocked by policy拒绝，未执行删除；缓存、原始资料与验证证据均保留，没有换方式绕过。

## 2026-09-20 最新仓库深度分析完成

- 本轮fetch确认fix/reliable-evaluation与origin均为da2fb8e，main仍为d5753b4；没有新增远端提交，未推送。运行文件本地差异仅为已完成的四处2026.1默认路径切换。
- 在03_analysis/08_全量156题优化与技能总结.md追加源码架构、历史结果重算、优先问题、赛题页码对应和后续验收顺序；保留此前实验记录并标注历史边界。
- 重算156个唯一题目：baseline101、agent最终110、均通过93、均失败38、改善17、退化8；单题记录耗时合计13884.799秒。首次94、修复成功16/62、原样重复15/62和失败阶段来自历史失败分析，完整原始日志本机缺失。
- 核对真实2026.1日志：此前缺许可证时sim_fail/synth_fail两项被负例脚本记为通过，但整次回归为失败；许可配置后已出现预期非零mismatch和RTL综合错误。提出环境错误单独分类与加强负例判据，未修改运行代码。
- 两个临时目录中的离线mock探针确认：综合工具退出0但没有成功标志/产物时仍可通过；run_problem复用非空目录会覆盖旧baseline。临时探针未新增项目脚本；本轮没有模型API、全量、GPU或容器重测。
- 同步AI_CONTEXT.md、PROJECT_STATE.json、PROJECT_STATUS.md，消除当前摘要中“E盘路径待修/未运行2026.1集成”的过时表述；39项自动测试与5项真实EDA回归属于此前同日升级验证，修复流程为mock且跳过综合。
- 重审目录，本轮仅更新五份既有分析/状态文档，无新项目中间产物。原始资料、历史输出、暂停的10/156批次及stash均保留；此前策略阻止的缓存清理没有绕过。

## 2026-09-13

- 用户明确确认队伍 45561 已从高云 J280 改报 AMD，当前赛题为 AMD 题目一“RTL/HLS 本地智能体设计赛道”的 RTL track。
- 修正项目中沿用 2026-09-01 旧证据边界而产生的过时状态；`PROJECT_STATE.json`、状态文档、AI 上下文和交接文档均改为以 AMD 为当前方向。
- 高云 J280 报名截图、作品名和方案说明继续保留为历史证据；不删除、不改写成 AMD 报名证据。
- 新版 AMD 报名截图尚未归档，后续可用于补强档案，但不再作为继续 AMD RTL 开发的前置条件。

## 2026-09-10

- 在 E 盘本地开发副本完成评测可靠性优化，分支 `fix/reliable-evaluation`，未推送远端。
- 修复 TimeoutExpired 部分输出为 bytes 时的崩溃；仿真拒绝矛盾的 Mismatches 计数以及 ERROR/FATAL 日志。
- 修复循环按通过状态和验证阶段选择候选，不再用退步的末次代码覆盖较好的尝试；保存完整尝试证据及 baseline 评测日志。
- 结果 schema 升至 2：无功能验证时通过率为 null；不足 5 个样本时 pass@5 为 null；记录 mock 模式和技能文本哈希。
- 批测提前校验三元组，保留子目录防止同名题覆盖，逐题原子保存汇总与 complete 状态；增加 baseline 对照、改善/退步题数和平均耗时。
- 更新 README、容器冒烟断言和项目状态；新增 6 项回归测试，全部 14 项测试通过。未重测真实模型、Vivado、Docker 或 ROCm，未宣称性能提升。

## 2026-09-01

- 归档 AMD 2026 选题指南、团队讨论截图和队伍 45561 完整报名页；重新生成 PDF 文本、元数据和 15 个源文件哈希清单。
- 新增 D-002：按用户授权开发 AMD 题目一 RTL track，同时保留高云 J280 已验证报名事实，不虚构官网改报。
- 安装用户级 Python 3.12.10；在现有 WSL2 中安装并验证 Docker Engine 29.7.2。
- 从 Canonical 官方 OCI rootfs 校验并导入 `amd-rtl-local/ubuntu:22.04`；构建 `amd-rtl-agent:dev`，断网 mock 冒烟通过。
- 将已固定 commit 的最小 CPU llama.cpp runtime 和许可证纳入镜像；最终镜像 `a449bd5e...80841f`（4,645,865,911 字节）在 `--network none` 下通过真实模型 `/health`、最短聊天请求和 mock agent 闭环。
- 实现标准库单文件 RTL agent、严格 baseline、Vivado 编译/仿真/综合入口、有限修复、pass@1/pass@5 和 VerilogEval 接入。
- 固定 VerilogEval v2 commit `c498220d0a52248f8e3fdffe279075215bde2da6`，确认 156 组三元组。
- 编译 CPU `llama-server` commit `010be9683afabe14ce299197b38c329f94bae568`。
- 下载并校验 Qwen2.5-Coder-7B-Instruct Q4_K_M：4,683,073,536 字节，SHA-256 `509287f78cb4d4cf6b3843734733b914b2c158e43e22a7f4bf5e963800894d3c`。
- Python 8 个单元测试通过；Vivado 正负 fixture 验证通过；真实 Qwen CPU 在 3 个无歧义公开题上通过 baseline 与 agent 单样本仿真。
- 识别并记录 VerilogEval 上游数据不一致：`Prob031_dff` 端口方向冲突、`Prob034_dff8` 未声明初值却由参考/测试要求初值；这些失败不伪装为模型错误或成功。
- 修复阶段增加一条通用端口方向矛盾诊断；只根据仿真日志与候选代码判断，不读取参考答案/测试台，不按题号特判。
- 为 Zynq UltraScale+ MPSoC 器件包生成精确增量安装/验证脚本；用户完成 AMD 认证和 UAC 后，首次下载因 CDN SSL/连接超时失败，脚本增加最多 4 次有限重试后安装成功，`xczu3eg-sbva484-1-e` 查询计数为 1。
- `tools/check_environment.ps1` 返回 `ENVIRONMENT_CHECK=PASS`；在 `xczu3eg-sbva484-1-e` 上完成编译/展开/仿真/综合，功能 fixture 为 `Mismatches: 0`，含时钟 fixture 的 5 ns（200 MHz）时序约束全部满足，并生成 DCP、时序和资源报告。
- 修正新 PowerShell 会话可能优先命中 WindowsApps 空 `python.exe` 别名的问题；环境检查现在优先使用已安装的 Python 3.12 实际路径，8 个单元测试复验通过。
- 初始化 Git `main` 分支并发布到公开仓库 `https://github.com/854259/FPGA`；首次导入提交 `ad143eb` 使用 `854259 <3260548169@qq.com>`。上传前排除模型权重、生成缓存、认证日志及含团队/第三方隐私的原始截图和群聊，原文件仍保留在本机。
- 向 GitHub 用户 `nzh152-lang` 发出 `854259/FPGA` 的 Write 协作者邀请；邀请 ID `331205643`，当前状态为等待对方接受。
- ROCm 实测及赛事方尚未发布的官方镜像/隐藏题集/最终接口保持待办，不写成完成。

## 2026-08-22

- 建立项目资料目录和 AI 同步规范。
- 归档 5 份厂商选题指南 PDF。
- 归档 2 张群聊技术截图；核验与 QQ 原图 SHA-256 一致。
- 保存群聊原始摘录。
- 使用 `pypdf` 生成逐页 UTF-8 全文和 PDF 元数据。
- 生成源资料 SHA-256 清单和资源链接索引。
- 完成五家赛题第一轮新手可行性分析。
- 形成短名单：安路选题一、易灵思赛题四、安路选题二。
- 保持最终选题状态为“未决定”。
- 部署 33 个项目文件到 `D:\HUST\IC\FPGA`，相对路径和 SHA-256 全部一致。
- 归档队伍 45561 报名截图。
- 将选题状态更新为：高云 J280“基于 FPGA 的实时姿态控制系统”，作品“凌衡实时姿态控制系统”。
- 新增 `DECISIONS.md`，严格区分报名事实、拟实施方案和未完成工作。
- 归档中科亿海微 2026 FPGA 赛道指南，新增逐页文本、元数据、资源入口与专项摘要。
- 归档 15:38–17:03 群聊补充摘录；将“成员回复 OK”保留为待核验入队状态，将“学数电”记录为计划而非完成。
- 将资料统计更新为 6 份 PDF、11 个原始源文件；高云 J280 的已确认选题和报名状态保持不变。
- 归档外部队伍 46576 的 AMD 报名截图并建立队伍身份边界；资料统计更新为 12 个原始源文件，我方仍为队伍 45561、高云 J280。

## 2026-09-12 当前机器验证
- 在 E:/26qiansai/FPGA-teammate-review 执行；历史 D 盘目录在本机不存在。
- E:/vivado/2025.2/Vivado/bin：固定 AND 样例编译、展开、仿真、综合通过，Mismatches: 0。证据：04_project/amd_rtl_agent/outputs/local_preflight_20260912。
- 14 项单元测试通过。新增可选 LLM_ENABLE_THINKING 参数及 run_cloud_smoke.ps1；云端 Qwen3.6-27B 真实闭环仍待用户在已配置临时密钥的 PowerShell 中启动，不能称为云端验证通过。

## 2026-09-12 本轮复测
- Python 3.11.9 下运行全部 14 项单元测试，全部通过（1.617 秒）。
- 固定 correct.sv 样例在当前 E 盘 Vivado 2025.2 下完成编译、展开、仿真、综合，各步骤退出码为 0；Mismatches: 0。
- 测试日志：04_project/amd_rtl_agent/outputs/retest_20260912/correct。
- 当前进程未配置 LLM_API_KEY，未执行云端真实模型测试；以上结果不代表模型生成通过率。

## 2026-09-12 API 接入入口
- run_cloud_smoke.ps1 支持读取当前进程/用户级 LLM_API_KEY，缺失时在终端隐藏输入；密钥不写入项目文件。
- 保留现有 Qwen 服务地址、qwen3.6-27b 模型和真实模型 + Vivado 测试入口；Python 改为使用当前环境命令。
- PowerShell 语法检查通过。当前机器未配置密钥，尚未验证 API 连通性或真实生成结果。

## 2026-09-12 云端真实模型测试通过
- 用户在终端输入密钥并启动 run_cloud_smoke.ps1，qwen3.6-27b API 已验证连通。
- outputs/cloud_smoke_20260912_225041/result.json：mock_model=false，baseline_pass=true，单个 agent 样本首次生成通过编译、仿真和综合，无需修复；进程退出码 0，总耗时 118.891 秒。
- 证据目录位于 04_project/amd_rtl_agent/outputs/cloud_smoke_20260912_225041。
- 本次仅为 AND 门题目的真实模型冒烟测试，不代表公开题集通过率；pass_at_5=null，真实模型修复分支未触发。此前待密钥/待云端验证记录为历史状态。

## 2026-09-12 公开数据集就绪
- 已获取 NVlabs/verilog-eval 并固定到 c498220d0a52248f8e3fdffe279075215bde2da6。
- dataset_spec-to-rtl 的 156 组题面、参考和测试台完整。
- benchmark --limit 20 按排序选择 Prob001_zero 至 Prob020_mt2015_eq2；本轮仅核对数据，尚未运行 20 题模型评测。

## 2026-09-12 20 题评测入口
- run_cloud_smoke.ps1 新增 -Benchmark20：前 20 题，每题 baseline + 1 个 agent 样本，最多 1 次修复，完整 Vivado 编译/仿真/综合。
- 语法及 20 组三元组完整性检查通过；输出独立 cloud_benchmark20 时间戳目录并汇总通过数量。
- 当前进程及用户环境无 API 密钥，需要用户在终端隐藏输入后启动；20 题评测尚未开始。

## 2026-09-12 云端公开集前 10 题结果
- 按用户最新要求停止于前 10 道完成题；已终止正在运行的第 11 题及其子进程，未计入统计。
- Qwen3.6-27B，VerilogEval v2 固定版本前 10 题：baseline 10/10，agent 10/10；每题 1 个 agent 样本，均首次通过，无修复。
- 两种生成均完成 Vivado 编译、仿真和综合；mock_model=false。10 题耗时合计 1125.189 秒（约 18.75 分钟），不含中断题。
- 原始 benchmark.json 保持 complete=false、requested_problems=20；另存 summary_first10.json 记录用户缩减范围后的结果，不把原 20 题任务标成完成。
- 证据：04_project/amd_rtl_agent/outputs/cloud_benchmark20_20260912_225725/summary_first10.json。
- 此结果仅适用于前 10 题，不能外推完整 156 题通过率；两种方式均满分，尚未体现技能提示或修复的增益。

## 2026-09-12 GitHub 同步
- 按用户要求同步 fix/reliable-evaluation 分支，纳入可靠性修复、云端入口与前 10 题精简报告。
- 提交前重跑 14 项自动测试全部通过；运行输出、权重、数据集副本和密钥不纳入提交。

## 2026-09-13 优化与完整本地回归

- 延续当前 E 盘项目和昨天已接通的云端 API；保留 Qwen3.6-27B 前 10 题 baseline/agent 均 10/10 的历史成绩。本轮未调用云端 API。
- 修正批量统计：schema_version=3，improved_problems 表示相对 baseline 改善；repaired_problems 只统计首个 agent 样本初次失败后实际修复成功的题目。单题格式仍为 2。
- API 空内容、异常响应结构统一明确报错，不额外重试；批量题数拒绝零和负数。
- Python 自动回归 18/18 通过；真实 Vivado 回归 5/5 符合预期：正确代码通过综合，编译/仿真/综合负例分别在预期阶段失败，固定模型响应驱动的修复流程由仿真失败恢复通过。
- 首轮发现旧 synth_fail.sv 实际可综合，已更换为仿真语法合法但时钟不明确的负例，并完整复测。首轮失败记录保留，不覆盖。
- 修复流程使用固定响应和真实 Vivado，不表示真实云端模型修复能力已验证；ROCm 本轮未测。
- 可复现入口：04_project/amd_rtl_agent/tests/run_vivado_regression.py；指定 VIVADO_BIN 和新的 --output-dir。
- 精简报告：04_project/amd_rtl_agent/bench/results/local_regression_20260913.json；完整日志：04_project/amd_rtl_agent/outputs/regression_20260913_verified。

## 2026-09-13 第 11–20 题云端评测准备

- 用户明确要求测试后 10 题；增加 --offset 与 -BenchmarkNext10，严格选择固定公开集第 11–20 题，保留原完整 20 题运行中的 seed 编号。
- 20 项自动测试通过，PowerShell 语法检查通过；固定数据集版本仍为 c498220d0a52248f8e3fdffe279075215bde2da6。
- 当前进程/用户环境均无密钥，准备交互终端隐藏输入后启动。尚未产生新的云端成绩。

## 2026-09-13 第 11–20 题云端验证完成

- Qwen3.6-27B，固定 VerilogEval v2 第 11–20 题：baseline 10/10、agent 10/10；每题 1 个 agent 样本，均首次通过，无修复。真实 Vivado 编译、展开、仿真、综合各阶段退出码均为 0。
- 本轮 complete=true，进程退出码 0，题目耗时合计 1099.498 秒（约 18.32 分钟）。完整证据：04_project/amd_rtl_agent/outputs/cloud_benchmark11_20_20260913_091816。
- 模型参数、技能提示哈希、完整验证模式与昨日一致。两轮独立汇总后前 20 题 baseline 和 agent 均 20/20；本地共有 156 组完整题目，剩余 136 题未评测，不能外推全量通过率或宣称修复增益。
- 精简报告：04_project/amd_rtl_agent/bench/results/qwen_cloud_next10_20260913.json；合并报告：04_project/amd_rtl_agent/bench/results/qwen_cloud_first20_combined_20260913.json。
- 昨日中断的原始 20 题报告保持 complete=false，不覆盖历史记录。此前待密钥记录已由本条完成状态取代。

## 2026-09-13 全量 156 题复盘与 skill 优化完成

- 原始 156 题全部完成：baseline 101/156，agent 首次 94/156，最多一次修复后 110/156；修复成功 16 题，相对 baseline 改善 17、退化 8。此前“剩余 136 题未测”为历史状态。
- 最终失败：格式 4、编译 6、展开 1、仿真 35；62 次修复中 15 次代码未变。复盘脚本与证据：04_project/amd_rtl_agent/bench/analyze_run.py、bench/results/full156_failure_analysis_20260913.json。
- 提炼并接入生成 skill 与仅修复时加载的 RTL_REPAIR_SKILL.md：变量声明、作用域、精简完整代码、时序、状态机和基于反馈的修复；不含参考答案。两份技能分别记录哈希。
- 修复日志保留首个错误和最终统计；相同阶段优先保留仿真错误比例更低的候选。24 项自动测试通过。
- Qwen3.6-27B 定向复测 5 题（同模型参数和原 seed，1 个样本、最多 1 次修复）：旧版 1/5，新版 3/5。Prob030 首次通过、Prob054 修复通过、Prob001 保持通过，均完成真实 Vivado 仿真和综合；Prob039 与 Prob108 仍编译失败。
- 定向成绩证据：04_project/amd_rtl_agent/bench/results/optimization_subset_20260913.json；详细复盘：03_analysis/08_全量156题优化与技能总结.md。
- 该样本按失败类型选择，只能说明局部结果；新版 156 题全量成绩未测，不外推通过率。本次变更未发布。

## 2026-09-13 编译驱动修复与重复检测验证完成

- agent 根据 Vivado VRFC 10-1280 报错，将简单 ANSI 输出声明中的对应 output/output wire 修正为 output reg，保留位宽、符号、方向与逻辑；宏、参数化及复杂声明不自动修改。修正占已有修复次数，仍需完整 EDA 验证。
- 同一样本内按精确代码哈希检测重复，重复的格式/编译失败复用已完成诊断，下一次模型提示明确指出原样返回。超时、工具缺失和仿真不缓存。记录 source、duplicate_of_attempt、evaluation_reused、model_calls。
- 30 项自动测试通过。两道历史失败代码 Prob039、Prob058 重放均由编译失败经一次声明修正通过真实 Vivado 仿真和综合（分别 Mismatches: 0 in 114 / 219 samples）。
- 本轮使用归档候选替代模型响应，没有调用云端 API；这是修复控制逻辑验证，不是新的模型成绩，不能合并进旧 156 题通过率。模型配置未切换。
- 复现入口：04_project/amd_rtl_agent/tests/run_declaration_regression.py；精简证据：04_project/amd_rtl_agent/bench/results/declaration_regression_20260913.json。未发布。

## 2026-09-13 批量实验续跑与统计

- 新增 benchmark --resume，按完成题检查点恢复，核对模型配置、代码/skill、题目/测试台/参考内容哈希和结果文件。未完成题在 restart_N 新目录重跑；保留中断证据。
- 输出目录防覆盖、单写入进程锁；旧实验无配置清单时不冒充可续跑。恢复不依赖可能尚未写完的总报告，而使用逐题原子检查点。
- schema_version 4 新增模型调用数、生成耗时与 EDA 耗时；未完成题历史尝试耗时未计入汇总。旧批量启动器改用独立尝试目录，执行异常题可重新运行。
- 39 项单元测试通过（包括中断、检查点先于总报告保存、配置/数据变化、结果篡改、目录锁、秘密字段不落盘）；真实 CLI 两题 mock 首跑与续跑一致。证据：04_project/amd_rtl_agent/bench/results/resume_regression_20260913.json。
- 用户计划国庆租 RTX 5090 一周测试 Qwen3.8-27B，当前仅计划，尚未租用/部署。GPU 与云端模型本轮未测；AMD ROCm 验证仍需单独完成。

## 2026-09-13 GitHub 同步完成

- 智能体优化、skill、156 题报告及续跑测试已推送至 fix/reliable-evaluation；已核对远端代码提交 6abfdd96d2550d24ff347bc9a5d0637a9a34fbdd。
- 合入 origin/main 的 d5753b4，保留用户已确认改报 AMD RTL 的最新状态；主分支未被覆盖。
- 当前自动测试 39 项通过，本轮没有新增真实云端/GPU 成绩。原文中“未发布”为当时状态，本条记录为最新同步结果。


## 2026-09-20 仓库拉取与分析

- D 盘主目录已切换至 origin/fix/reliable-evaluation 的 da2fb8e；远端 main 仍为 d5753b4。未推送。
- 最新核心代码本机自动测试39/39通过；历史精简报告逐条重算为baseline101/156、agent最终110/156。完整原始全量日志不在本机；新版修复代码尚无全量成绩。
- 本机旧批次 qwen36_api_full156_20260913 仍为10/156、complete=false，暂停状态保持；与远端历史全量实验分开。本轮未调用API、未运行Vivado集成或GPU评测。
- 拉取前15个文件的本地改动保存在stash de9254643da829767e8bacb3ee57a5c633a4718f；已恢复无重叠的资料和排除规则，重叠代码尚未合并。
- 待处理：旧启动器固定E盘Vivado与本机F盘不符；旧批量入口缺少整批版本一致性保护；综合通过不代表逐题满足200MHz。详见03_analysis/08_全量156题优化与技能总结.md末尾本日分析。

- 已重审工作目录。删除 __pycache__、dfx_runtime.txt 和空异常目录的清理命令被自动审批以 blocked by policy 拒绝，未执行删除；缓存及目录保留，原始资料、模型和历史评测输出保留。git diff --check 通过，核心代码与远端相同。


## 2026-09-20 Vivado 2026.1 升级准备

用户明确要求立即升级。已确认 AMD 官方提供2026.1 Windows安装器，本机现有F:/vivado/2025.2，F盘可用约100.8GB。官方下载入口已打开，当前等待用户在AMD网页登录；尚未下载安装包、安装或切换工具。拟在F盘并存安装2026.1，安装后验证目标器件与编译/仿真/综合。原2025.2及暂停评测保持。

- 2026-09-20 后续：用户完成AMD登录，下载页面显示Signed In User。已进入2026.1安装包姓名/地址验证表；机构、真实地址等必填信息缺失，等待用户补全。尚未下载或安装。

- 2026-09-20 安装包已到位：F:/Downloads/FPGAs_AdaptiveSoCs_Unified_SDI_2026.1_0616_1700_Win64.exe，300277378字节，MD5=9e315e7b98310a8816d8eb3184ffd1ad，与AMD官网Verify Download一致。自解压静默启动失败，已校验7z头及长度并用py7zr解压至F:/vivado/Downloads/Installer_2026.1；原安装包保留。xsetup.bat报告需要管理员权限，已请求Windows提权，尚未安装或变更现有2025.2。

- 后续提权：首次隐藏PowerShell请求返回Windows取消，未启动。改为直接以RunAs启动可见xsetup.exe，Start-Process成功，PID3912；安装是否完成仍待核验。

- 2026-09-20 16:04安装尝试失败：reAuthenticate返回HTTP500 Internal Server Error，安装器回滚退出；无java/xsetup进程，新版vivado.bat不存在。尚不能判定与VPN有关。用户已明确不保留旧版，待2026.1验证通过后卸载2025.2。当前重开安装器重新登录尝试。


## 2026-09-20 2026.1安装完成，许可证待配置

安装器日志18:43:31明确显示Installation completed successfully，新版位于F:/vivado/2026.1。实际回归中xvlog/xelab成功，xsim明确报告缺少Simulator许可证，Vivado启动报告无有效许可证；不能标记环境验证通过。证据：04_project/amd_rtl_agent/outputs/vivado_2026_1_regression_20260920。负例阶段匹配不能证明正常仿真/综合能力。AMD官方2026.1许可说明要求生成免费Vivado Basic许可，下一步配置许可后复验。旧版待新版验证后卸载，暂停评测未恢复。


## 2026-09-20 Vivado 2026.1许可证配置及验证通过

通过AMD官网生成免费Vivado Basic Node Locked许可证，保存在用户.Xilinx目录，未纳入仓库；配置用户级XILINXD_LICENSE_FILE。许可证条目到期日期2027-09-20。显式使用新版路径和许可路径运行真实EDA回归，5/5通过：正确设计编译/展开/仿真/综合、编译负例、仿真负例、综合负例和mock模型修复流程；目标xczu3eg-sbva484-1-e，仿真Mismatches: 0。证据：04_project/amd_rtl_agent/outputs/vivado_2026_1_licensepath_20260920/summary.json。此前失败目录保留为排障证据，不合并为通过记录。没有调用模型API或恢复暂停评测。旧2025.2尚未卸载，项目历史默认工具路径切换尚待处理；本条仅确认2026.1安装、许可及显式路径回归完成。


## 2026-09-20 默认路径切换与旧版卸载

四个执行入口已切换F:/vivado/2026.1/Vivado/bin；用户VIVADO_BIN及Path同步，新进程生效。39项自动测试通过。AMD官方2025.2卸载日志显示Uninstall completed successfully，旧主目录已不存在，新版仍存在。F盘可用空间由50130616320增至129391996928字节，约释放73.8GiB。许可证网页已关闭；额外提权取消，许可证管理器窗口、少量.xinstall/2025.2残留与安装缓存尚未清理；临时维护脚本清理命令被策略阻止。证据05_handoff/environment/vivado2025_uninstall.log。未恢复暂停评测。


## 2026-09-21 本机新版单次修复全量评测启动

用户提供全量运行命令，已在独立目录 E:/26qiansai/FPGA-repairfix-eval 使用 GitHub 10bddd9 启动 Qwen3.6-27B、156题、1样本、最多1次修复评测。原工作区未提交修改保持。57项单测和本机 Vivado 2025.2 的5项真实EDA回归通过；首题模型返回已进入EDA，全量尚未完成，不能报告新版通过率。输出：04_project/amd_rtl_agent/outputs/qwen27b_repairfix_r1_new；启动进程49784，退出码和运行日志位于同级outputs目录。


## 2026-09-21 新版156题评测完成

已核验退出码0、complete=true及156个唯一题目的单题结果。Qwen3.6-27B，1样本，最多1次修复，本机Vivado2025.2：baseline 100/156（64.10%），agent首次 92/156，最终112/156（71.79%）；修复成功20题，相对baseline改善18题、退化6题，净增12题（7.69个百分点）。最终失败阶段：{'simulation': 35, 'format': 2, 'compile': 4, 'elaboration': 3}。模型调用367次，单题耗时合计约3.90小时。历史110/156仅作参考，未进行新旧代码同期配对实验，不将差值直接归因于本次代码改动；单次修复未验证回退后再次修复收益。精简报告：04_project/amd_rtl_agent/bench/results/repairfix_r1_20260921_summary.json。


## 2026-09-21 新版156题离线复盘完成

逐题审核44道失败、6道退化和13次完全相同源码修复；救回20题中7题来自自动声明修复、13题来自55次模型修复。发现候选编译位宽警告未进入后续仿真修复反馈。真实Vivado自检复现099参考接口不匹配、156参考自比零错误但测试台截止。原始112/156不变，未调用模型或修改运行代码/skill/数据集；完整复盘见03_analysis/09_新版156题离线复盘_20260921.md。


## 2026-09-21 GitHub优化交接材料

按用户要求同步新版全量成绩、44题复盘及可移植诊断证据；更新AI_CONTEXT/AI_HANDOFF并新增OPTIMIZATION_HANDOFF_20260921.md供队友继续优化。运行代码、skill、测试数据和历史成绩保持。上传范围仅为明确列出的文档与精简JSON，不包含密钥、模型或outputs缓存。
