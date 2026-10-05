# 位数值映射提示后缀小试：准备草案

本目录基于封存的 phase_full156_20261005 44 份源文件，采用其中原 P 的 phase 功能策略作为 C/P 共同策略。首轮与修复均保留原 8192 tokens、最多一次模型修复、每题绝对 300 秒外部监督、原 extractor、原输入、原官方评分和零重试。没有引入 driver/xelab、table、诊断优先级或额外 native 预算。

唯一臂差是 runtime.skill_texts 的返回值：C 返回原生成技能 G 和原修复技能 R，P 返回 G+A 和完全相同的 R。A 是 APPENDIX.txt 原 UTF-8 390 字节，包括末尾一个 LF，SHA256 为 518a93fef56513e39467b67be1031c23fd1bf37ed9bcc1a672aa050e82dc6bce。G 原末尾已有 LF，故直接 G+A，不加入额外分隔符、不 strip、不改 A 字节。首轮系统消息为 C:G、P:G+A；修复轮为 C:G+LF+R、P:G+A+LF+R。原技能文件字节保持，transport 使用同一个 wrapped G 验证所有消息。

4 个目标是 082/086/097/124，6 个守卫是 045/054/058/071/112/115；按实际 INPUT_MANIFEST task ID 排序，交替 C/P 顺序，20 个 fresh 样本，最多 40 个真实请求。首稿可能因系统提示不同而变化；审计只描述首稿 SHA 是否相等，不设置同首稿门槛，也不将不同首稿的全部收益归因于某一次修复。

仅当完整 20 样本证据有效、无错误/超时/未确认/回退、至少 2 个目标的官方系数提高、6 守卫两臂均 L3 且 P 调用数不增加、均分提高及总 P 请求不多于 C+2 时，才允许下一次新全量实验。原 phase 全量资格保持；本小试不能提供独立验证、five-sample、部署或全量收益证明。

最新完整 phase 全量的实际 archive/spec/auditor SHA 见 BASELINE_BINDING.json。四目标的真实动机绑定为 raw_evidence/BIT_MAPPING_SUPPORT.json，SHA256 77a8a0bcd2fb1e649f4da1efe03ec0ec1a4ebc63bf413af628bd70cdcfdbbb2b；最新 43 题失败报告 REVIEW/BINDING 的原字节只作为私有 metadata。题号规则、旧答案、参考 RTL、官方 TB、控制解释以及这些元数据均不进入模型。模型仅获得原提示、原技能、当前候选、原实际诊断和 A。

实际只读环境捕获及保护源清单已复制到 raw_evidence/ENVIRONMENT_CAPTURE.json 和 PROTECTED_GROUPS_CAPTURE.json；当前捕获含 10 组、330 份源文件（含 driver v1 和 v2），运行时按捕获数据计算组数和集合，不硬编码后续目录。每组提供真实 cloud_root 和 local_root；本机校验使用 local_root，云端使用 cloud_root。原 stage 资源检查处增加只读源保护核验，共 41 个位置。

prepare.py 是待 root 审查后调用的冻结入口，需要 --base-commit、--environment-capture、--protected-groups、--priority-report 四项真实参数；现有 metadata 已固定为当前捕获。此准备没有 RUN_SPEC，也没有安装、FIFO 提交、模型或 EDA 执行。必要本机 FAKE 测试和 sourceproof 的实际结果见 raw_evidence/LOCAL_PREPARATION_RECEIPT.json；测试通过只说明边界实现，并不表示收益已测。
