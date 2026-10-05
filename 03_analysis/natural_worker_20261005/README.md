当前主任务状态：五项源已冻结于 `TOOLS_SPEC.json`（10734654），ROOT逐字节比较原adapter的证据见 `ORIGINAL_ADAPTER_RECEIPT.json`。本机3.12.14与云端3.12.3各52项纯工程测试通过；Windows实际两个junction控制、Linux实际两个symlink控制，分别由RESULTS/LINUX_RESULTS及Linux收据记录。0真实HTTP、模型、EDA或新FIFO任务，真实接口/硬取消/native反馈/隔离及质量门槛保持未完成。下文描述原型的范围与局限。

# 自然题目 worker：FAKE 工程原型

仅在本目录工作，复用同字节 immutable `adapter.py`，SHA-256 为 `9b41ef3adfd345ff037ee4dcd3ef918d991c3bc5e52562ed8bc309355e0a39f9`；原 adapter 未修改。`worker.solve` 是直接函数，只接收显式标记 `io_kind='FAKE'` 的注入传输和编译函数，没有真实 HTTP、模型、EDA、队列或云端客户端。C/P 只是共享文件/消息边界的原型分支标签，目前没有分支求解策略差异，不是官方 baseline，也不是已合格的 P 或既有冻结候选的同源实现。

包内测试自包含：用明确已冻结的 immutable SHA 常量核对本目录 adapter 字节，不访问兄弟目录。主任务在冻结时另行将包内 adapter 与原工作树文件逐字节比较并保存 receipt。当前 `test_worker.py` SHA 为 `bbe5afa1214baf9b35d6a1778d45bee6afafe1f2f2f5e8aefb6ff056e1549753`，`worker.py` SHA 为 `852f346daa444098c1743634b4649a7589f507b6dd8c95d1a92d212d372d9647`；完整四源绑定在 `RESULTS.json` 和 `DRAFT_RESULT.md`。

两分支都通过原 adapter 使用原 `input.prompt/context` 和全部空输出路径：不传 harness、答案、task ID 或 categories。首消息包含原 Unicode/换行、全部公开 partial/helper/doc 和完整 JSON `files` 输出协议，不改原模块为 TopModule、不截取模块、不补缺文件。第二次请求只在首稿所有目标完整、候选编译失败已确认且实际诊断与编译输入 SHA 绑定后发出，绑定原输入、之前全部候选文件和该条原诊断；不接触隐藏 judge 反馈。格式不完整或缺/多/重复文件时直接停止，保留首回复，不能用格式修补当新采样。

固定请求上限 2 次、每次 `max_tokens=8192`、`temperature=0`、`top_p=1`，一个 solve 使用同一 300 秒 deadline；每次 FAKE 回调收到剩余秒数，返回后立即检查 deadline，文件核验/诊断写入后的收尾及最终摘要写入后再检查。最终已观察到的耗时达到 300 秒时降为 `solve_timeout`，保留已有证据，不能留下通过状态。超时、未确认、`length` 结束、异常、无诊断或输入哈希不匹配均停止，不重试、重采样或重置预算。同步回调须遵守剩余时间：原型通过假时钟验证 deadline 传播和超限停止；真实 HTTP/子进程硬取消尚未集成，不能称真实 300 秒强制终止已验证。

所有任务内容和证据强制写入本目录忽略的 `raw_evidence/` 内的全新 run 目录，拒绝已存在目录或恢复重跑。先同字节物化原公开 context，再为每轮单独物化全部公开文件；仅指定输出可替换 partial，其余 helper/doc 保持原字节。拒绝越界、绝对/平台/保留设备名、大小写别名、文件/目录冲突，以及路径组件中的物理 symlink/junction。编译前后核对文件清单和 SHA；修改或新增链接仍保留失败现场，停止后续请求。

编译回调仅收到公开候选/context HDL 的物理路径、SHA、所有输出路径和源码/header 清单，公开 docs 已保存但不作为 HDL 传入。不会传 prompt、隐藏测试、答案或 task ID。所有公开 HDL helper/header 都保留；检测到 `include` 且安全隔离未验证时明确 `compile_abstained`，不悄悄丢依赖。FAKE capability 仅用于工程测试；即使在该假分支，宏 include、危险路径、缺少的依赖或无法安全解析的 operand 也弃权。当前 include 扫描保守且不是完整预处理器，任何真实编译仍需实际隔离证明。

每次调用前保存 request JSON 和消息哈希；收到回复即保存完整 UTF-8 字节、返回状态和 SHA。transport/compiler 的传入对象均保存调用前、调用后 canonical JSON 双快照和 SHA，回调返回或抛异常后都核对；原地修改 messages、预算、candidate/helper 文件参数时明确 `callback_input_mutated`，保留原返回或异常、请求/编译部分证据并停止后续请求。未能序列化的后对象单列表示并拒绝，不当成相同。这只检测传入参数对象的变化，**不证明外部 transport 忠实发送了保存的请求，也不证明真实编译器使用了保存的参数、timeout kill 或系统隔离**；`external_callback_fidelity_verified=false` 始终保留。

每轮保留全部文件及清单、编译输入/回执、实际诊断及各自 SHA，原输入 binding 始终相同。摘要持续写入，部分回复、编译异常、超时和文件污染会留下已有证据；`fake_candidate_compile_pass` 仅是注入回调的工程结果，`quality_verified=false`，实际模型/EDA/原生测试均为 0。

本机 Python 3.12.14：52 个测试，0 failure、0 error、0 skipped。覆盖预算、超时/未确认/不重采样、物理路径和链接、context/helper/doc、全部目标、缺/多/重复文件、首/次消息绑定、实际诊断来源与输入 SHA、原输入变更拒绝、部分证据保留；新增六个恶意参数突变控制，覆盖两种 transport 突变、两种 compiler 突变及双方突变后异常，另有诊断写入/最终摘要超限两控制。两次实际物理链接测试均使用 Windows junction；该宿主无法创建普通 symlink，普通 symlink 仍需支持宿主实测。精确收据位于 `raw_evidence/TEST_RECEIPT.json`，公开汇总和源码 SHA 位于 `RESULTS.json`；执行 `run_checks.py` 只跑合成 FAKE 控制和本地文件系统链接设置，不编译真实 RTL。

尚缺原 ANSI early-return、既有 native runtime/functional feedback、C/P 真实策略、HTTP 请求终态确认、真实编译/runner/judge、原工具逐次 argv/rc/blob/XML 记录、真实进程取消与清理、include 隔离、曝光审查及全部质量门槛。此时没有自然题目解题数、原 harness 成绩、独立模型或采用结论。交付后等待主任务审阅，不执行真实调用。
