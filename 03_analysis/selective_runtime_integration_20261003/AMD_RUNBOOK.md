# AMD 执行说明：同一原型的三阶段验证（UNRUN）

本说明交给已有本地 SSH 执行任务。云端只准备文件；以下命令尚未执行，不能作为编译、清理或提分证据。保留原型 `773d4ce` 与旧实验。本轮交付的完整提交号以 GitHub 提交／PR 回执为准，执行前填入 `DELIVERY_SHA`，不要使用浮动分支名。

## 1. 固定源文件，沿用已有 SSH

在已有本地仓库取得本轮提交，用纯 Git 导出下面的文件。通过既有 SSH/SCP 将 tar 和提交标签放到 AMD 新隔离目录；不新建密钥，不切换共享 kit 的工作树，不覆盖既有运行目录。原型、测试夹具与 oracle 应保持这个完整相对目录布局。

```bash
DELIVERY_SHA=填入本轮完整40位提交号
git fetch origin codex/selective-runtime-linux-preflight
git archive --format=tar --output=selective-followup.tar "$DELIVERY_SHA" \
  03_analysis/selective_runtime_integration_20261003 \
  03_analysis/r2_signedness_20261003/input/Prob115_shift18 \
  03_analysis/r2_signedness_20261003/probes \
  03_analysis/r2_selectivity_20261003/guards \
  04_project/amd_rtl_agent/submission
printf '%s\n' "$DELIVERY_SHA" > DELIVERY_COMMIT
sha256sum selective-followup.tar
```

上传沿用已有已核验主机与授权账户；不要把本机私钥、许可证或模型权重加入归档。AMD 解包到例如 `/workspace/team/runs/fpga_teammate/selective_followup_<唯一ID>/source/`，保存 `DELIVERY_COMMIT` 于 source 根。校验 tar 的传输 hash，再解包，不在原 kit 目录解包。

## 2. 核对资源、身份与工具

已有 SSH 执行者先检查当前实验、`/workspace/team/SLOT.lock`、磁盘、内存、模型 PID/启动时刻、当前服务别名、端点及实际工具版本。历史 PID 不可直接复用。既有 lease 若被占用，等待该所有者自行释放；不删除别人的锁。

包装器将再做两次准入核验：已知评测／EDA 进程为空，当前 PID 拥有端点监听 socket，`/health` 正常、`/v1/models` 别名匹配、`/slots` 明确空闲，官方 baseline 双 hash 匹配。随后使用原 `slot.sh acquire/release`，记录正式 package、判定器和完整题集的前后 hash。所观测的题集身份须由执行者与现有实验清单对照；“未变化”不等于“版本已获认可”。

`/slots` 不可用、进程身份未知或源文件不匹配会拒绝启动。**不要为了通过守卫启用新服务、重启模型、改官方基线或关闭实例。** 保留失败输出，由同一执行入口补充空闲观测方法和新的静态修订后再试。

历史工具路径为 `/workspace/AMD/2026.1/Vivado/bin`，kit 为 `/workspace/team/tasks/autodl-rtl-kit/project`；执行者必须确认当前实际值。沿用已有许可证／运行库绑定，不输出其内容。若当前 SSH shell 缺少这些绑定，只使用该实例已配置的路径；不得安装或替换依赖。

## 3. 后台串行执行

将下面六个参数换成刚核验的实际值。`SOURCE_ROOT` 为隔离导出目录；`NEW_RUN_ROOT` 必须尚不存在，与 source 分开。示例中的模型名称和 PID 都是占位符。

```bash
SOURCE_ROOT=/workspace/team/runs/fpga_teammate/selective_followup_<唯一ID>/source
NEW_RUN_ROOT=/workspace/team/runs/fpga_teammate/selective_followup_<唯一ID>/results
KIT_ROOT=/workspace/team/tasks/autodl-rtl-kit/project
MODEL_PID=填入当前核实的PID
MODEL_NAME=填入当前核实的模型别名
VIVADO_BIN=/workspace/AMD/2026.1/Vivado/bin
BASE="$SOURCE_ROOT/03_analysis/selective_runtime_integration_20261003"
nohup bash "$BASE/launch_linux_followup.sh" \
  "$SOURCE_ROOT" "$NEW_RUN_ROOT" "$KIT_ROOT" "$MODEL_PID" "$MODEL_NAME" "$VIVADO_BIN" \
  </dev/null >"${NEW_RUN_ROOT}.driver.log" 2>&1 &
DRIVER_PID=$!
printf '%s\n' "$DRIVER_PID"
ps -p "$DRIVER_PID" -o pid,ppid,stat,etime,comm
```

启动后立即确认后台 PID、首份 `guard-engineering/status.json`、`stage.log` 和实际日志增长；只有启动回执不能证明任务已运行。SSH 断开后沿用同一目录只读查询，禁止重复启动。启动脚本每一阶段重新核验并持有现有 slot，阶段失败就停止；单阶段硬上限 2400 秒，租约 60 分钟并预留清理时间。错误目录保留，不自动调整预算或补采样。

## 4. 预期结果与阶段门

1. **工程矩阵**：7 个 run_job 场景与 3 个自有进程拓扑；真实 xvlog 与默认 20／5／6 秒预算。编译成功能采用可编译新稿；语法错误、客户端超时和时间不足保留原稿；声明修复成功出口复查实际接受源码。进程身份在外层收尾后逐项消失或明确记录复用，僵尸／活动后代不算消失。`engineering/summary.json` 的 `complete/passed/cleanup_verified=true` 才进入下一阶段。默认 31 秒是准入量，30／31 秒运行因先消耗初始调用和编译时间而应跳过；实测工具超过 5 秒会使矩阵失败，不能偷偷扩大 cap。
2. **正确稿负对照**：先由真实独立 oracle 确认原稿零失配、错误新稿存在功能失配，再仅在隔离 selector 夹具中强制 review。现有原型预期会采用可编译的错误逻辑稿；如实记录 `functional_regression_detected`、`regression_protection=false`、`deployment_blocked=true`。这里 `passed=true` 仅表示负对照完整且有效，绝非功能保护通过。任何不符合预期的行为留证调查，不继续第三步。
3. **小配对**：先验证 8 套规格的 16 个正负 oracle 控制，然后 10 检查点各 O0,D0,C0,C1,D1,O1，共 60 行；最多 12 次复查尝试，无补采样。新 11／17 位正确稿和五份旧守卫应旁路；选择器弃权须如实记录。全部输出冻结后才离线评分实际候选。统计 C/D 相对 O 的修复、改坏、调用尝试、收到响应、token/cache/finish、D−O 和 D−C 增量秒数。**没有预设提分结果**。

工程成功与功能负对照成功也不等于正式验收。当前脚本未覆盖真实 Vivado 的全部后代拓扑、换组后代、原子替换附近的强制中断、共享服务取消或完整 HTTP 题面生成成本。这些列在报告 `uncovered` 中，不由父进程退出码补成已通过。

## 5. 日志、停止与回滚

```text
<NEW_RUN_ROOT>.driver.log
<NEW_RUN_ROOT>/DELIVERY_COMMIT
<NEW_RUN_ROOT>/guard-{engineering,functional,paired}/resource_check.json
<NEW_RUN_ROOT>/guard-{engineering,functional,paired}/status.json
<NEW_RUN_ROOT>/guard-{engineering,functional,paired}/stage.log
<NEW_RUN_ROOT>/engineering/{summary.json,tool_logs/,process_*/receipt.json,*/receipt.json}
<NEW_RUN_ROOT>/functional/{summary.json,oracle_*/,forced_correct_review/,normal_correct_bypass/}
<NEW_RUN_ROOT>/paired/{start.json,controls/,generated/,generation_complete.json,grades/,summary.json}
```

`guard` 状态中的 `passed`、`own_slot_released`、`protected_files_unchanged`、`model_unchanged` 及 `owned_cleanup.verified` 必须核对，不只看 driver 返回码。模型仍忙或清理不确定时，包装器保留本轮锁并注明 `slot_retained_for_inspection`；由原执行者查清本轮剩余进程和服务状态，再通过原 slot 入口释放自己的锁，禁止宽泛 pkill、killall 或重启共享模型。不要以客户端退出证明共享服务已取消推理。

回滚只需弃用这个隔离研究目录或 revert 新增材料；正式包和模型从未被此脚本部署替换。保留失败目录与冻结原件。发现、补丁及脱敏 summary 应继续同步 GitHub，精确标注执行提交和原始日志 hash；上传前去除私有路径、主机与凭据信息，不覆盖旧证据。未经实际判定不能写“提分”，有稳定收益后再单独规划 156 题回归和独立来源题验证。
