# 队友自然题有效信号补强：原始证据复核

只读下载FIFO60的RAW_EVIDENCE.zip（65bc05bf…，1280332字节）及POSTFLIGHT.zip（08bca1a5…），339份原始清单文件逐SHA、路径与唯一性验证；复用并核对自己冻结的FIFO55原档案613文件及原审计，与队友59结果完全一致。未执行队友stage/auditor，0新增模型/EDA。可复现入口review.py，结果RESULTS.json。

原gray_to_binary测试没有读取valid，虽然原题面要求该信号；错误valid恒0在原五次测试全部通过。队友60保留原题面、RTL控制、端口、参数和其他测试，只在既有等待之后的断言区新增`assert dut.valid.value == 1`。改版测试与原版的差异已按字节及AST复核，全部控制都标记original_harness=false。

修改后的六控制各跑五次：正确稿全部通过；恒0、恒1、identity、valid恒0四类错误稿各五次失败；单故意断言的失败传播对照五次失败。30次实际编译和30次实际仿真的工具路径/SHA、argv/返回码、候选和编译blob、每次新XML、stdout/stderr、外层pytest/退出码、原参数及终态guard逐项绑定。五次覆盖四种不同配置，默认配置重复两次，不能当成五个独立设计。

这一条断言修复了有限研究测试的漏检。原数据、原测试SHA及版本排除表保持，不把修改后的研究结果算作原官方判定器成绩，也不扩大至全CVDP有效或模型优化通过。0独立实际模型、eligible_for_independent_models=false、adoption=false。完整156资格、忠实原ABI/context和曝光审查仍待完成。

队友规格沿用原owner的identity/frozen_at和16控制/50编译保险上限；实际新cloud_root及5fe49dd3…规格SHA、六控制/30命令明确区分本次实验，不将旧时间当新冻结时刻。外部工具/依赖与进程保护由历史现场记录约束，无新的断网、R9700或32GB认证。

顺带只读查阅队友57的原FSM复核：143第二稿仅增一条注释，执行RTL没变，768/2048失配仍在；逐端口反馈的收益尚未实测。该条为已有报告交叉引用，没有运行新模型实验。
