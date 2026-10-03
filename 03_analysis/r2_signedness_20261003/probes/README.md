# R2 题面独立探针

仅根据本实验冻结的三个题面编写；没有读取官方测试台或参考实现。它们是开发探针，不能证明所有输入或真实隐藏测试均正确，也不反馈给模型。

| 题目 | 检查数 | 检查范围 | 手写负控制 |
|---|---:|---|---|
| Prob115_shift18 | 31 | 首先 load；正/负位模式算术右移1/8；左移1/8；load优先；四模式 ena=0 保持；连续右移；全零与全一 | 右移错误地补零 |
| Prob042_vector4 | 256 | 穷举全部8位输入，以整数补码转换核对32位结果 | 零扩展 |
| Prob055_conditional | 4096 | `{00,01,02,7e,7f,80,fe,ff}` 四输入笛卡尔积，覆盖最小值位置、相等和有符号边界 | 将四输入当 signed 比较 |

115 不要求未指定的上电初值。输入在低电平中途改变，在上升沿后1ns检查。042 用整数减256作为独立于拼接的期望值；055 使用32位零扩展数核对。正控制和负控制均为手写，只用于检查探针能接受预期正确实现并拒绝预定语义错误。

Linux 的 Vivado `xvlog`、`xelab`、`xsim` 应已在环境路径中，许可证与运行库由调用方设置：

```text
python -B probe_runner.py validate-controls --out /new/controls_directory
python -B probe_runner.py candidate --task Prob115_shift18 --solution /path/solution.v --out /new/candidate_directory
```

`probe_candidate(task, solution, outdir)` 返回并保存 `result.json`。状态为 `pass`、`fail` 或 `environment_error`，有每阶段命令、退出码、时长、日志SHA256与检查/失配数。负控制必须正常编译、展开、仿真完成且 `failure_kind=semantic_mismatch`；编译失败不能算探针有效。每阶段60秒，超时仅终止由该子进程新建的进程组，不触碰模型或其他进程。

`validate-controls` 在新目录保存 `controls_validation.json`：`complete`、`valid`、`assets_unchanged`、`probe_files` 和三题 `tasks[task] = {positive, negative, valid}`。`probe_files` 固定执行器及9份SV的哈希；各结果保留原始日志和输入副本。已有目录拒绝覆盖。

运行器的本地行为测试使用模拟工具输出，不替代真实六次控制验证。真实Vivado控制验证由主执行者运行后归档，生成实验必须等待它全部通过。
