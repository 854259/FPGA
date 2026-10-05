# 工程原型结果：52 个纯测试通过，真实集成待审阅

Python 3.12.14 本机运行 `run_checks.py`：52 tests、0 failures、0 errors、0 skipped。包内 adapter 字节与明确已冻结的 immutable SHA 常量一致，原件未修改；测试不读取兄弟目录，自包含工具包可独立运行。主任务冻结时另行逐字节比较包内 adapter 与原工作树文件并保存 receipt，不将这项外目录比较冒充本次测试。四份 Python 源可解析，完整源码 SHA 和准确测试收据分别在 `RESULTS.json`、忽略的 `raw_evidence/TEST_RECEIPT.json`。两次实际物理链接控制是 Windows junction；普通 symlink 创建在该宿主不可用，其实测仍待。

| 源文件 | 当前 SHA-256 |
|---|---|
| adapter.py | `9b41ef3adfd345ff037ee4dcd3ef918d991c3bc5e52562ed8bc309355e0a39f9` |
| worker.py | `852f346daa444098c1743634b4649a7589f507b6dd8c95d1a92d212d372d9647` |
| test_worker.py | `bbe5afa1214baf9b35d6a1778d45bee6afafe1f2f2f5e8aefb6ff056e1549753` |
| run_checks.py | `d151ebb973042585795f37d51b1d5542d9e6741d050d4a09468005e235365678` |

已验证的都是工程边界：C/P 同首请求和原 public 输入；所有输出和公开 helper/header/doc 物化；partial 仅在指定输出路径替换；缺/多/重复文件拒绝；危险物理路径、文件冲突和实际 junction 拒绝；请求 2 次上限及 8192/0/1 固定参数；同一 300 秒 deadline 的剩余预算传递；超时/未确认/异常不重试；第二稿必须绑定完整前稿、原输入和该轮确认诊断；请求、回复、全部文件和编译输入/回执 SHA 可重建；部分失败、回复和污染现场保留。

审阅补齐六个恶意 FAKE 回调控制：原地修改 transport messages/max_tokens、compiler candidate/helper 参数，及双方突变后异常。调用前后 canonical 对象双快照与 SHA 均保留，变化后 `callback_input_mutated`，保留原返回/异常及已有文件，停止第二次请求。这个检查仅检测对象变化，不能声称保存请求与外部实际调用一致；也不证明真实 timeout kill、编译参数使用或系统隔离，`external_callback_fidelity_verified=false`。

另补两项收尾 deadline 控制：诊断写入和最终摘要写入耗尽 300 秒均把假通过降为 `solve_timeout`，保留回复、编译回执和诊断证据。此为同步 FAKE deadline 协议测试，仍不证明真实进程硬取消。

所有 transport/compiler 都是 FAKE；没有真实 HTTP、模型、EDA、隐藏测试、答案、task-ID 求解逻辑、FIFO、云端或部署。真实题目内容未写入公开文件；worker 强制把任务内容写入本目录的忽略 `raw_evidence/`。实际模型、EDA、native tests 均 0，`quality_verified=false`、`eligible_for_independent_models=false`、`adoption=false`。

尚未接入：原 ANSI early-return、native runtime 和 functional feedback、真实 C/P 策略/候选、模型回复终态/成本、原编译及 native runner/judge、逐原工具 argv/rc/blob/XML 审计、真实同步调用的硬取消和清理。当前 deadline 测试验证假时钟与回调预算协议，不验证真实进程 300 秒强制终止。

include 安全隔离没有真实证明。未验证 capability 时明确弃权；假 capability 测试也拒绝宏或缺失依赖，保留所有公开文件。原型保守文本扫描不能证明原预处理器/搜索路径安全，真实集成前必须补齐隔离，不能把 helper 丢掉来编译。此结果不是官方 baseline、已合格 P、同源冻结候选、自然质量或独立模型成绩；等待主任务源审阅后再决定集成。
