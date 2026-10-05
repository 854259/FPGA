> 历史准备说明：主任务后续已冻结44资产并通过双环境纯检查/依赖保护预检，当前实际状态以README、RUN_SPEC及收据为准；下面保留冻结前记录。

# 准备结果：未运行真实原生校准

新增本目录的 6 份可执行源码：同字节 parser、同字节 tool journal、纯 `calibration.py`、守卫要求的 `stage.py`、只读完整 `audit.py`、`test_preparation.py`。固定 14 项为正确稿、11 类语义错误、明确故意失败、全模块/五角色改名正确稿；原题面、14 份 RTL/14 份 TB 及完整绑定放在忽略的 `raw_evidence/`。已交付旧草稿目录没有继续编辑。

本机 Python **3.12.14：16 方法、82 子检查，0 失败、0 错误**。核对 parser `94bcb3…`、journal `ec07a0…` 原 SHA；14 份完整 native ABI 与生成 69 观察/138 双输出值；控制文本的复位/历史/单输出/常量/互换/脉宽/延迟/时钟区别；全部改名绑定；明确 sentinel 标记和 rc1 约束；未知 rc、截断及坏路径拒绝。两份完整合成档案分别验证“鉴别通过”和“错误误通过但证据完整”，七类工具/源码/blob/行/guard 篡改拒绝。新增10个全局额外/移位/未知收据变体、19个 attempted/actual/unconfirmed/count_error 摘要变体均拒绝；10个阶段末尾计数异常撤销成功、保留非空 error，并通过 finally 异常取消待返回 rc0。部分未确认尝试继续明确失败且不重试。所有合成收据、工具身份及编译 blob 均是虚构 fixture，**没有执行 RTL**。

审计独立要求全局恰好 **28 收据**、14 预定控制目录各一份 iverilog/vvp；换目录或改文件名不能隐藏原生收据结构。`actual` 和 `attempted` 编译/仿真各14、`unconfirmed_native_attempts=0`、无 `journal_count_error` 才允许完整证据。阶段成功路径先确认同一约束，finally 若计数异常则撤销完整/鉴别资格并终止非零。修订前后14 RTL/14 TB、两份 prompt 和控制 manifest 共31文件逐 SHA 保持。

计划真实 **14 iverilog + 14 vvp**；当前 **0 实际模型、0 EDA、0 原生命令、0 SSH、0 FIFO**。没有创建真实 `RUN_SPEC.json` 或 collector/guard，来源未冻结。root 下一步审查源码、固定工具和依赖、生成保护清单与收集器、通过自己的 wholeFIFO guard 实测并审计。不得跳过未知失败或自动重试。

完整观测/执行证据与控制鉴别资格保持两个字段；wrong 必须 semantic mismatch+rc1、positive 必须 semantic pass+rc0、sentinel 必须完整零失配+唯一故意失败标记+rc1，任何误通过留在结果并使鉴别资格 false。本测试是 `generated_research_test=true` 的题面研究测试，`original_harness=false`，不冒充原判定器得分。当前真实控制鉴别 **false/待实测**，独立质量准入 **0**，adoption=false，亦无模型泛化或最终资格结论。

接口与固定顺序详见 `README.md`；纯检查准确收据见 `LOCAL_CHECKS.json`。工具日志使用 standalone stdout/stderr/full compiled blob，不需要或伪造 Cocotb XML。
