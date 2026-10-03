# 选择性复查隔离原型：独立审阅记录

日期：2026-10-03。范围：只读核对源码、测试、原始日志与冻结回执；本轮仅新增此脱敏报告。

## 当前结论与来源

审阅分支为 `feat/official-rtl-contract`。最新 HEAD 与用户给出的交付版本一致：`773d4ce7d142fd04a0592caa86d3bdc6d46786c9`。在这一固定版本，预算、失败回退及原子采用机制已有工程证据；功能退化保护、默认时限的真实工具适配及 Linux 后代清理覆盖仍未验证，不能据此宣布功能修复率或全量提分。

关键源码 Git blob SHA：

- 原型 `package/agent/runtime.py`：`d3e1e5532ba98a42641bc505834d9320099f20d3`；交付记录的文件 SHA-256 为 `318672f841430a864cd99fae4de712942258d0dcda7a1ad6b0567c71610f52c8`。
- `tests/test_selective_runtime.py`：`1e597d0ca72f0e8bd028f846f029620452c7c712`。
- `tests/fake_compiler.py`：`1b489d03c8e4400f5e1865b686112e916584eedf`。

主要来源：[交付结果](https://github.com/854259/FPGA/blob/773d4ce7d142fd04a0592caa86d3bdc6d46786c9/03_analysis/selective_runtime_integration_20261003/RESULT.md)、[验证摘要](https://github.com/854259/FPGA/blob/773d4ce7d142fd04a0592caa86d3bdc6d46786c9/03_analysis/selective_runtime_integration_20261003/validation_summary.json)、[源码清单](https://github.com/854259/FPGA/blob/773d4ce7d142fd04a0592caa86d3bdc6d46786c9/03_analysis/selective_runtime_integration_20261003/source_manifest.json)、[最终 receipts](https://github.com/854259/FPGA/blob/773d4ce7d142fd04a0592caa86d3bdc6d46786c9/03_analysis/selective_runtime_integration_20261003/local_receipts.json)、[22 项原始日志](https://github.com/854259/FPGA/blob/773d4ce7d142fd04a0592caa86d3bdc6d46786c9/03_analysis/selective_runtime_integration_20261003/local_test_log.txt)、[42 项原始日志](https://github.com/854259/FPGA/blob/773d4ce7d142fd04a0592caa86d3bdc6d46786c9/03_analysis/selective_runtime_integration_20261003/related_test_log.txt)及[下一步草案](https://github.com/854259/FPGA/blob/773d4ce7d142fd04a0592caa86d3bdc6d46786c9/03_analysis/selective_runtime_integration_20261003/LINUX_PREFLIGHT_NEXT.md)。先行失败 receipts 保留为历史，不混入最终成功回执。

两个原始日志分别记录 `Ran 22 tests / OK` 与 `Ran 42 tests / OK`，支持工程方所述 64 项本地集成／相关检查通过。它们是本地假模型、受控编译器及相关源码检查的证据，不是 64 个竞赛样本。该轮摘要记录真实模型调用、真实 Vivado 调用均为 0。

本轮对最终 JSON 重新计数：45 份 case receipt、22 个唯一测试名、合计 75 次假服务 POST，与摘要一致。26 个可选请求 hash 核验为工程方交付的检查结果；本轮读取核验逻辑，未运行 `verify_evidence.py`，未重新执行测试或工具链，也不把 trace 的预算尝试数当成真实服务收到数。

## 已实现的工程机制及收益

[runtime L877–883](https://github.com/854259/FPGA/blob/773d4ce7d142fd04a0592caa86d3bdc6d46786c9/03_analysis/selective_runtime_integration_20261003/package/agent/runtime.py#L877-L883) 的普通编译成功和声明修复成功两个出口都调用 `finish_compiled`，传入当时实际接受的源码。[L620–628](https://github.com/854259/FPGA/blob/773d4ce7d142fd04a0592caa86d3bdc6d46786c9/03_analysis/selective_runtime_integration_20261003/package/agent/runtime.py#L620-L628) 用 `repairs - attempt` 决定剩余调用预算：默认 `RTL_REPAIRS=1` 时，首答成功可占用第二次尝试做一次复查；模型编译修复已经占用第二次尝试后，不再额外复查。

[L650–667](https://github.com/854259/FPGA/blob/773d4ce7d142fd04a0592caa86d3bdc6d46786c9/03_analysis/selective_runtime_integration_20261003/package/agent/runtime.py#L650-L667) 与 [L711–728](https://github.com/854259/FPGA/blob/773d4ce7d142fd04a0592caa86d3bdc6d46786c9/03_analysis/selective_runtime_integration_20261003/package/agent/runtime.py#L711-L728) 传递剩余绝对 deadline 并处理客户端／编译失败；[L730–746](https://github.com/854259/FPGA/blob/773d4ce7d142fd04a0592caa86d3bdc6d46786c9/03_analysis/selective_runtime_integration_20261003/package/agent/runtime.py#L730-L746) 将新稿写到同目录临时文件后用 `os.replace` 切换，采用前保留完整旧稿。相关故障测试支持受控条件下的回退，采用 trace 同时标注 `functional_improvement=unverified`。

这带来的直接收益是限制额外调用、明确复查与编译修复竞争同一预算，并在复查工程失败时保留已编译原稿。默认 off、observe 不发复查请求以及 C/D 的提示差异有本地检查支持；这不证明接入开销为零、正式部署通过或真实功能收益。

## 边界一：工程失败回退不等于功能退化保护

当前版本的 [test17 L358–363](https://github.com/854259/FPGA/blob/773d4ce7d142fd04a0592caa86d3bdc6d46786c9/03_analysis/selective_runtime_integration_20261003/tests/test_selective_runtime.py#L358-L363) 将 `>>>` 改成 `>>`，仍返回该候选，采用原因是 `static_and_compile_gates_only`。最终 receipt 也记录该用例 `status=accepted`、`functional_improvement=unverified`。工程结果文档已经披露这一边界，不应称其隐瞒。

静态完整性、接口一致、禁止文件访问、子模块和独立编译门只能证明相应工程条件，不能证明符合题意。这个用例从既有问题稿出发，不能直接当成“正确稿已被改坏”的功能退化实证；它足以说明采用门没有独立的功能正确性保证。

[test05 L251–258](https://github.com/854259/FPGA/blob/773d4ce7d142fd04a0592caa86d3bdc6d46786c9/03_analysis/selective_runtime_integration_20261003/tests/test_selective_runtime.py#L251-L258) 的正确候选和守卫主要验证 selector 的 skip／abstain 旁路。只证明正确稿没有被选中复查，不能覆盖正确稿一旦进入复查后的退化路径。

最小补充：先用独立 oracle 确认一份正确稿，再仅在隔离测试夹具中强制选择结果为 review；让假模型返回同接口、可真实编译但在负值移位等边界上错误的新稿，核对采用状态和最终功能。强制仅用于测试采用门，不修改生产选择器或把隐藏参考送入模型。若仍采用，应如实记录“无功能退化保护”，不能用 skip 守卫的成功替代这一负对照。功能评价在生成完成后离线执行。

## 边界二：默认 31 秒准入未实测适配真实工具

[runtime L435–438](https://github.com/854259/FPGA/blob/773d4ce7d142fd04a0592caa86d3bdc6d46786c9/03_analysis/selective_runtime_integration_20261003/package/agent/runtime.py#L435-L438) 默认模型／编译／清理保留为 20／5／6 秒，[L622](https://github.com/854259/FPGA/blob/773d4ce7d142fd04a0592caa86d3bdc6d46786c9/03_analysis/selective_runtime_integration_20261003/package/agent/runtime.py#L622) 合计 31 秒作为准入条件。集成测试在 [L141–143](https://github.com/854259/FPGA/blob/773d4ce7d142fd04a0592caa86d3bdc6d46786c9/03_analysis/selective_runtime_integration_20261003/tests/test_selective_runtime.py#L141-L143) 覆盖为 3／3／1 秒；[L312–330](https://github.com/854259/FPGA/blob/773d4ce7d142fd04a0592caa86d3bdc6d46786c9/03_analysis/selective_runtime_integration_20261003/tests/test_selective_runtime.py#L312-L330) 部分故障用例进一步缩为 0.5 秒。

因此本地检查支持预算分支和超时回退，不支持“默认 31 秒已适配真实 xvlog／模型”。31 秒是配置上的准入保留量，也不是实测成本或吞吐结论。真实工具冷启动、候选编译和收尾耗时可能改变可复查比例；具体影响尚未知。

最小补充：先使用自有假模型与真实 xvlog，按默认配置记录正确候选、语法错误候选和预算边界的完整时间、命令、版本、返回码与日志 hash；同时报告复查准入／跳过数量、旧稿保留和下一正常请求是否恢复。真实模型的响应成本另行冻结测量，不能用本地受控回复耗时替代。

## 边界三：Linux 后代发现与消失核对仍需补齐

[runtime L481–501](https://github.com/854259/FPGA/blob/773d4ce7d142fd04a0592caa86d3bdc6d46786c9/03_analysis/selective_runtime_integration_20261003/package/agent/runtime.py#L481-L501) 的递归发现读取各父进程主线程的 children 文件，未枚举所有线程；[L504–533](https://github.com/854259/FPGA/blob/773d4ce7d142fd04a0592caa86d3bdc6d46786c9/03_analysis/selective_runtime_integration_20261003/package/agent/runtime.py#L504-L533) 对已发现 PID 核对 starttime 后发信号，但只等待直接子进程，没有逐后代消失的完成核对。这是源码自称的 best effort，并非“所有清理必然失败”。

[L403](https://github.com/854259/FPGA/blob/773d4ce7d142fd04a0592caa86d3bdc6d46786c9/03_analysis/selective_runtime_integration_20261003/package/agent/runtime.py#L403) 为 worker 建独立会话，[L351–365](https://github.com/854259/FPGA/blob/773d4ce7d142fd04a0592caa86d3bdc6d46786c9/03_analysis/selective_runtime_integration_20261003/package/agent/runtime.py#L351-L365) 的外层 `killpg` 是兜底。阶段子进程继承 worker 的组；仍在该组的后代可能由外层清理，因此不能只看内层发现限制就宣称遗留。反过来，也不能仅凭父进程返回码证明后代已结束。

[test13 L321–330](https://github.com/854259/FPGA/blob/773d4ce7d142fd04a0592caa86d3bdc6d46786c9/03_analysis/selective_runtime_integration_20261003/tests/test_selective_runtime.py#L321-L330) 与 [假编译器 L13–19](https://github.com/854259/FPGA/blob/773d4ce7d142fd04a0592caa86d3bdc6d46786c9/03_analysis/selective_runtime_integration_20261003/tests/fake_compiler.py#L13-L19) 覆盖父子都存活时的受控超时；[test21 L421–439](https://github.com/854259/FPGA/blob/773d4ce7d142fd04a0592caa86d3bdc6d46786c9/03_analysis/selective_runtime_integration_20261003/tests/test_selective_runtime.py#L421-L439) 覆盖外层等待期间的 deadline 和父 worker 结束。已交付日志来自 Windows，未覆盖 Linux 父先退孤儿、多线程派生或真实 Vivado 后代。

最小补充是在隔离夹具中保存 worker、客户端、工具及后代的 PID、starttime、PGID，核对阶段结束与外层收尾后各身份是否终止／消失；对仍存在的僵尸或脱离组的进程明确记录状态，不能只核对父 rc。未观察到的后代拓扑标为未覆盖。客户端退出也不证明共享模型取消，服务端取消状态仍为 unknown。

## 建议的最小 Linux 矩阵与功能对照

以下均为后续建议，不是本轮已执行结果；现有前测草案已包含其中多项，本报告补足具体证据缺口。

| Linux 工程场景 | 最小核对证据 |
|---|---|
| 自有假服务＋真实 xvlog，正确／语法错误候选，普通与声明修复两个出口 | 默认时限、准入与跳过、命令／版本／rc／日志 hash、实际接受源码、四字段 HTTP 回包及下一正常请求 |
| 受控慢工具：父子同时活、父先退留子、多线程派生后代 | 每个本轮所属身份的 PID／starttime／PGID，阶段与外层清理后逐项核对；换组边界仅在自有夹具中观察并如实报告 |
| 复查等待、编译等待及临时写入／替换附近的外层中断 | 最终文件为完整旧稿或完整新稿；后代及组收尾证据；未注入的时刻明确未测试 |
| oracle 已确认的正确稿强制进入 review，返回可编译错误稿 | 静态采用记录与离线功能负对照；与正确稿 skip 守卫分别报告 |

工程矩阵通过后再冻结 O/C/D：O 不复查；C 同一选择器普通复查；D 同一选择器加符号清单。同一底座、技能、候选、模型配置、调用与时间预算、采用门；固定输入 hash、oracle、顺序和采样次数，保留失败，不能随结果调整选择器或补采样。

已知 115 只作开发烟测。至少加入未用于调整的规格家族及正确／错误配对、旁路守卫和上述强制 review 功能负对照；分别记录触发、预算跳过、尝试数、收到的请求／响应、实际候选、离线功能、token／cache／finish 与耗时。新构造题只证明机制迁移，不冒充独立竞赛题或隐藏题泛化。

检查点实验的 D−O 是该检查点接入总增量，D−C 是清单相对普通复查的增量，均不含首次生成。随后从题面开始的 HTTP O/C/D 才能测完整请求成本与真实触发率，不能沿用旧触发比例或扩大成全量提分结论。

## 同步理由、范围与回退

新增记录的意义是认可已交付的工程机制，并明确晋级功能／Linux 验证所缺的最小证据，避免把控制调用和失败保原稿混写为功能保障。潜在收益仍待对照验证；时限调整、清理实现或采用门变化需另冻结新版本，不能覆盖旧实验。

本轮仅连接器只读审阅和新增文档，未运行交付脚本、测试、推理或 EDA，未部署、SSH、操作服务器进程或向其他 AI 发消息。正式包、旧报告、原始日志与 receipts 保留；无新功能修复率、官方等级、全量分数或部署验收结论。撤回可单独 revert 本次文档提交，不涉及工程代码。
