# 整个评测任务先进先出

用户于2026-10-04明确选择“整个评测任务先到先得”。统一入口位于AMD服务器 `/workspace/team/tools/task-fifo-20261004/task_fifo.py`，队列状态在 `/workspace/team/task_fifo/`。按入口签发的序号执行：当前任务完整结束、完成收据通过且模型／工具／协作锁空闲后，才启动下一任务。没有按请求交错、优先级插队或自动重跑。

该入口只管整任务准入，任务内部仍使用原有`.gpu.lock`、SLOT资源守卫及超时清理。模型PID2013333、8000端口、slot.sh和现有任务源码保持；不增加并行推理、不重启服务、不删除对方锁或终止对方进程。原156题评测PID3061569原地登记为1号任务，仍使用原冻结版本；登记不是重启。

**生效范围：从统一入口提交的任务。** 旧脚本直接启动、直接请求8000或直接抢锁会绕过队列，必须由发起方改从此入口提交。当前没有覆盖或强制改写队友已冻结脚本，也没有声称所有旧入口已经迁移。这是共享准入机制，不是对所有直接端口调用的硬拦截。

提交示例（整个命令应是已有资源守卫保护的任务，并使用全新输出目录）：

```text
python3 -B /workspace/team/tools/task-fifo-20261004/task_fifo.py submit \
  --task-name <整轮名称> --cwd <工作目录> \
  --completion-json <整轮结束后写出的JSON路径> \
  --slot-owner-prefix <此任务的SLOT所有者前缀> \
  -- <已有守卫保护的整轮命令及参数>
```

提交立即返回票号和监控PID；未轮到时不启动命令。整轮结束JSON须`complete=true`，若有`passed`或`valid`也须为true。已经存在的结束收据不能用于新提交，防止误判完成。正常任务以退出码0加有效收据结束；异常保留队首和日志供检查，不把失败自动变成下一次抽样。

查看／取消未开始的任务：

```text
python3 -B /workspace/team/tools/task-fifo-20261004/task_fifo.py status
python3 -B /workspace/team/tools/task-fifo-20261004/task_fifo.py cancel-queued --ticket <票号>
```

运行中的任务不能用cancel-queued取消。失败队首经检查后可用`release-held --ticket <票号> --reason <检查结论>`归档放行；入口要求原任务PID已结束、模型／工具／协作锁空闲，不杀进程、不清资源锁。PID消失不会擅自认定任务成功。

已有任务只有在FIFO为空且PID身份仍有效时才能`adopt`；观察其自然结束和整轮完成收据，不重新运行它。队列接收顺序以加锁登记的递增票号为准，近同时提交由票号确定顺序。一次等待最长24小时，超时保留状态供检查。

AMD Linux四项检查使用真实CPU子进程及独立临时队列：逆序启动监控仍按1→2→3整项完成，失败保留队首／下一项不启动，未开始取消不执行，登记已有进程不重启。0模型／EDA，源码和测试日志已归档；这不是GPU性能或多队员实际接入验收。

共享台账：`/workspace/team/TEAM_ACTIVITY.md`；当前我们的进度、修改和结果摘要在`/workspace/team/activity/fpga_owner/STATUS.md`，每30秒更新。调用元数据／修改／结论分别为calls.jsonl、changes.jsonl、conclusions.jsonl。只记录自己的调用，原正文和参考留私有证据，不把阶段进度当作已审计新全量分。每位队员写独立命名空间，避免覆盖其他人的日志。

## 队友如何查看与记录

先看TEAM_ACTIVITY.md找到成员的STATUS；要追溯某次调用或修改，再查对应jsonl的证据路径及提交。Git中的 `03_analysis/task_fifo_20261004/` 是带时间的归档快照，服务器STATUS才是持续更新入口。

每次修改记录目的、文件、提交或源码SHA、影响、是否改动正式部署；每项结论记录测试版本／预算／样本数量、结果、已知限制、证据路径和后续动作。进行中的样本等级应标为进度；不得直接写成全量收益。调用观察时间与实际调用时间分开，当前回填记录只有观察时间。

成员可以用append入口往自己的命名空间记录修改或结论，data.json内填写上述字段（event-id选用提交号或固定实验编号，重复写入会去重）：

```text
python3 -B /workspace/team/tools/task-fifo-20261004/activity.py \
  --ledger-root /workspace/team/activity/<自己的名称> append \
  --kind changes --event-id commit:<提交号> \
  --summary "修改目的和影响" --data-json <自己准备的data.json>
```

结论使用`--kind conclusions`。目前自动观察器只接入fpga_owner当前评测，其他成员的修改和调用不会自动收录；各自记录后可在TEAM_ACTIVITY入口追加自己的STATUS路径。
