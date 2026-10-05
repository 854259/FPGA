# 通用多驱动修复说明：8 题独立小试准备

本目录仅准备；尚未冻结 RUN_SPEC、提交 FIFO、调用模型或 EDA，没有真实新样本或增益。根任务将在检查源码、捕获/核验环境及冻结后决定实际整任务提交。

C 与 P 共用一个 worker 和相同的旧65 P 控制策略：普通 xvlog 成功后做同一候选 xelab，成功再走原 phaseP 功能检查。P 唯一臂差是将真实多驱动诊断交给封口 `guidance.augment_diagnostics` 后返回；C 原诊断返回。只有实际 ERROR VRFC10-3818 与完整 procedural-drivers 文案触发说明，源 SHA `4891253991f3a0b1f23755698d079ba7a161dc7ccaa9ee4fae400bcc87a23a7a`。不改候选 RTL、extractor、首提示、token 数、原技能、修复次数或预算监督。ANSI 声明修补成功后的原提前返回保持。

8 个已知开发题固定为 133/156 两目标及 045/054/058/071/112/115 六守卫，C/P 各一个 fresh 首稿，完整 16 分母、8192、最多一次修复、原外层绝对 300 秒 owned 监督。保留全部首稿波动与失败，不重放、不重抽、不重试、不做 best-of。测试里的模型/native 均为 FAKE，本机纯检查不能代替真实测量。

审计重新绑定 request/reply、原 native rc/log、候选/source/tool、精确 repair payload 和外部官方成绩。目标因果链需要两臂首稿和候选相同、首轮实际 xelab 同3818事实失败，P 精确原诊断加 appendix 确实进入唯一修复，修复后真实 xelab0且官方系数严格提高。C/P 私有路径不同；只在审计比较中把收据绑定的候选绝对路径替成固定占位，其他错误事实逐字保持，原日志、原 SHA 和模型 payload 不变。共同 source proof 以封存旧 worker 字节和精确允许变换验证，不容许额外 worker 差异。

准入新 full 还要求完整16、无错误/超时/未确认/退步、六守卫均L3且请求数相同、P总新增请求最多2、均分提高。单独通过 xelab 或仅不同首稿得分增长不足以归因。旧65实际归档 `87e3d657…`、spec `87cb93c0…` 的 .775/.775 与 `qualified=false` 保留；先前 full/独立/五样本/采用资格不会由本试验自动改变。

`factor_proof.py` 验证共同 worker、guidance 原字节及其它旧源原字节。`prepare.py --base-commit <根任务核验的完整commit>` 是根任务将来显式运行的冻结脚本；本轮未运行。它使用根任务实际捕获的私有 `GUIDANCE_ENVIRONMENT_CAPTURE.json`，绑定4编译入口/环境/udev、18部署/936输入/35官方、完整模型身份和依赖。`protected_sources.py` 使用实际 `GUIDANCE_PROTECTED_GROUPS.json` 核验原8组/232源与各spec，包含 table `_v2`/`cc1abf90…`；新 stage 起终和每样本既有 gate 保存核验收据。旧 guard 自身没有这232源保护，新增保护在本 stage；根任务仍负责安装前后核验。

公开只保留必要源码、说明和元数据；首稿/修复回复、RTL、日志、题面和环境/保护快照在私有 raw 或实际结果归档。模型、EDA、SSH、FIFO、Git 实际操作均为0，公共结论维持准备状态。
