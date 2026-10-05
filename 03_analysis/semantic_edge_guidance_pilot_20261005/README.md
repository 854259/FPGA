# 逐边沿状态语义提示：未冻结草案

本草案从最新 phase_full156_20261005 的 44 份冻结源文件核对复制，以原 P 的 phase 功能策略为 C/P 共同策略。原输入、技能文件、extractor、runtime、官方判定、8192 输出上限、最多一次修复及每题绝对 300 秒外部监督保持。未引入位映射、编译诊断重排、写入归属、额外 elaboration、表格验证或新的 native 预算。

唯一臂差为 semantic_policy.install 包装 runtime.skill_texts：C 返回 G,R；P 返回 G+A,R。A 精确取自已固定的语义复盘提议，586 UTF-8 字节，含末尾一个 LF，SHA256 为 8728d9f3a6d32ee785082771d1c28a08d6c4dbfa59fc5daa55b93e191ddbba36。原 G 末尾已有 LF，直接追加，不 strip、不增加分隔行；首轮消息为 G 或 G+A，修复消息为 G+LF+R 或 G+A+LF+R。因此首轮和修复系统消息都改变，原修复技能字节不变。

8 个目标为 089、111、133、139、146、149、150、154；6 个守护为 045、054、058、071、112、115。按真实 task ID 排序并交替臂顺序，固定 14 题、28 个新样本，最多 56 次请求。终态审计要求 57 份连续源保护回执；不要求两臂首轮回复相同，也不把不同首稿的差异解释为同一首稿下的一次修复因果。

按 root 最新要求，完整 28 样本无错误、超时、未确认调用或回退，至少 3 个目标官方系数提高、均分严格提高、6 个守护两臂 L3 且 P 调用不增加、总 P 请求不超过 C+2，才能考虑一次新的全量回归。原语义复盘写的是更严格的跨三类/调用相等提议；该历史提议保留原字节，但不是本次实际 gate。本小试不提供部署、独立验证、正式五样本或新的全量分数证明。

题面与最终 RTL 的语义复盘、39 题分类和 SHA 行绑定只做私有 metadata。模型仅获得原题面/接口、原技能、当前候选、原真实诊断和通用 A；policy 只能读取 APPENDIX.txt。SOURCE_FACTOR_PROOF 从原 3fb1531c… RUN_SPEC、全 44 SHA 和上游 worker 的精确替换重算，终态 audit 必须与保存证明一致。

root 已实际提供 SEMANTIC_NEXT 环境和源保护捕获，当前 12 组、445 份源文件，包括实际已安装的 diagnostic 54 份组。精确字节复制为 raw_evidence/ENVIRONMENT_CAPTURE.json 与 PROTECTED_GROUPS_CAPTURE.json；较早 11 组捕获以 INITIAL 文件保留。运行时动态读取真实集合与数量；Windows 使用显式 local_root，Linux 使用 cloud_root，不删除版本后缀推断路径。prepare 还须核对 root 所供真实参数并逐摘要检查原上游及各组源文件。

prepare.py 仅是待 root 调用的冻结入口，需要 --base-commit、--environment-capture、--protected-groups、--semantic-review。草稿阶段没有 RUN_SPEC、没有安装或 FIFO 提交，也没有模型或 EDA 调用。必要纯测试包含 FAKE 传输/工具/判定及只读证据核对；通过仅证明接入边界，不证明增分。
