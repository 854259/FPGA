FIFO71 的完整测量有效，控制鉴别资格仍为 false。全部 75 条实际命令均已确认，20/25 控制匹配；15 个语义负例全部检出、误接收为零。五个 sentinel 的完整观测和致命诊断均已保留，但直接启动的 xsim 入口真实返回码全部为 0，不能改记为非零、补记为成功或放宽旧门槛。本次没有新增模型、EDA、SSH、FIFO 或 Git 操作，也没有新的得分证据。

| 题面 | cared 格 | constant0 失配 | constant1 失配 | 单格翻转失配 | sentinel 失配 / 直接 xsim rc |
|---|---:|---:|---:|---:|---:|
| 050 | 8 | 7 | 1 | 1 | 0 / 0 |
| 057 | 16 | 10 | 6 | 1 | 0 / 0 |
| 113 | 16 | 8 | 8 | 1 | 0 / 0 |
| 122 | 16 | 8 | 8 | 1 | 0 / 0 |
| 125 | 13 | 8 | 5 | 1 | 0 / 0 |

所有正例、语义负例和 sentinel 都完成 xvlog、xelab、xsim，三个工具各 25 次。语义负例的 rc=0 与正失配同时存在：物理进程正常结束不代表电路作对。`summary.passed=true` 表示完整测量封口，`qualified_for_generated_control_discrimination=false` 保留 sentinel 失败；两者不能互换。

本机只读复核了档案 443 个成员中的 442 个 manifest 成员 SHA、68 个归档及本机冻结源、全部 75 条 argv/cwd/source/compiler/environment/resource/spec/log/真实 rc 绑定。无额外 native receipt、pending、timeout、launch error、group signal 或存活进程组；guard 证明清理、模型与保护文件保持、自己的槽释放。既有 auditor 没有重跑。绑定如下，完整日志和逐命令数据只保存在私有 raw：

- RUN_SPEC：`cc1abf90fc1e38fbfcaf51df53eab0b47572c532dd8bcc91a334ed4cbfde9d74`。
- actual terminal archive：`af3cc0110d0370ff326df3e7946aec8f2d25a933dcef24b0037a3ef3c9cee121`。
- frozen auditor：`be7c8784dcc8254f7dc2b9ccaf0d9c37962097edd702a2cd91e3385b93935050`。
- actual RESULTS：`526f4def25193ff88e2102506464e8b2628889fb0b2fe3cab3f960e9610e043b`。

五次 sentinel 的实际 argv 都是 `/workspace/AMD/2026.1/Vivado/bin/xsim table_probe -runall -nolog`。各日志依次含 full care rows、唯一完整 `R2_PROBE_RESULT`、绑定 marker、`Fatal: OWN_TABLE_SENTINEL`、`$finish called`、`exit`。冻结 TB 的 `$fatal(1,"OWN_TABLE_SENTINEL")` 位于完整 summary 之后；既有 `owned_command` 收据直接保存 `proc.returncode`，没有把错误文本改写成返回码。能够确认的是：**这些具体调用的直接入口物理失败状态没有传播出来**。档案没有保存生成的 `xsim_script.tcl` 或内核单独物理退出码，因此不能确定实现根因，不能断言 xsimkernel 本身返回 0，也不能推广为所有 runtime error 都返回 0。

AMD UG835 2026.1（2026-06-23）说明 `-runall/-R` 执行 `run -all; exit`，`-onerror/-onfinish` 选择 stop 或 quit；该说明没有系统非零返回码约定。它与本次日志的停止/退出序列相容，这是解释范围的推断，尚非根因证明。[xsim 官方命令说明](https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/xsim)

`run -all` 可停于 runtime exception 等条件；`run -quiet` 明确可掩盖内部错误并返回 TCL_OK，因此候选控制不能使用它。官方亦说明 Tcl sourced-command 错误可由 `catch` 截获，但没有保证 `$fatal` 必然成为 Tcl error。[run 官方说明](https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/run)、[Tcl 错误处理说明](https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/Errors-Warnings-Critical-Warnings-and-Info-Messages)

只建议一个最小新因子：**预注册的 Tcl 数值执行状态由真实监督进程传播**。保留现有控制 RTL、研究 TB 与 care 行；另建冻结 Tcl batch，把 `run -all` 的实际 `catch` 数值结果及完整选项保存到新鲜、绑定本次 case/spec/Tcl 的状态文件，再明确退出。由独立监督进程保存直接 xsim 真实 rc、完整原日志和该状态文件，严格结合已存在的完整 care 解析，最后产生自身实际物理返回码。`-tclbatch` 执行命令文件有 AMD 官方支持；具体 fatal 后能否继续并得到 `catch=1` 尚须真实校准。[UG900 2026.1 的 Tcl batch 示例](https://docs.amd.com/r/en-US/ug900-vivado-logic-simulation/Using-a-tclbatch-File)

候选须另行预注册并实际运行以下四类，禁止用 `Fatal` 字符串直接驱动物理失败：

| 控制 | 数值/观测条件 | 待验证监督进程物理 rc | 独立保留的判定 |
|---|---|---:|---|
| positive | catch=0，全部 cared 观测已绑定且零失配 | 0 | 正例完整测量 |
| semantic wrong | catch=0，全部 cared 观测已绑定且预期正失配 | 0 | 测量完整，电路错误，不能误接收 |
| sentinel | catch=1，完整观测已绑定且零失配，无超时/启动错误 | 1 | wrapper runtime-contract failure；直接 xsim rc 原样保留 |
| unknown | 状态文件缺失/部分/未绑定、catch 非预期值、缺格/X/超时等 | 2 | unknown；不能升级成已证实 fatal 或生成反馈 |

若 sentinel 仍 `catch=0`，即便日志含 Fatal，也淘汰该因子，不启用字符串 fallback。`catch=1` 的脚本自身出错、环境故障或记录失败也不得冒充已证实 sentinel，必须靠完成状态文件、完整观测及独立正负控制排除。未来审计须分别盘点直接 xvlog/xelab/xsim 和监督进程的实际调用、argv、日志、状态文件与真实 rc；不能把外层 1 填入内层 0 的字段。

该因子验证的是新增监督进程能否传播数值 runtime 状态；若直接 xsim 仍为 0，旧 direct-xsim 资格门槛仍不成立，FIFO71 的 false 结论也不改变。它不构成模拟器失败证明、官方 TB 资格、parser/full-feedback 鲜样本收益或采用资格。后续任何提分仍需独立真实实验。本次只提出方向，没有实现或运行 Tcl/wrapper，没有改动冻结 68 源。
