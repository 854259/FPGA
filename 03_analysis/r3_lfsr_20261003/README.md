# R3 执行入口

状态：准备完成，尚未执行 EDA。先读 PLAN.md。无模型调用，无官方判定，也未读取官方测试台、参考实现或 verdict。

Linux/Vivado 环境准备并取得独占实验槽后，运行：

```text
python3 -B probes/run_probe.py --out /absolute/new/unique/r3_probe_run
```

工作目录可以任意；执行器默认引用自己同目录逐字节复制的 R2 helper。也可明确传入 `--helper /absolute/path/probes/probe_runner.py`，内容必须匹配固定 SHA-256。输出目录必须不存在。包装先检查正/负控制；控制有效才检查归档候选，因此最多三次 EDA。

结果 `validation.json` 分开记录 `controls_valid`、`valid`、`semantic_mismatch_observed`。退出 0 只代表协议和控制有效，不等于假设成立。必须查看归档候选 xsim.log 中 `R3_MISMATCH` 的首次实际失配，再归因具体边界。工具/编译失败不冒充语义失配，任一问题会保留日志。

本地已通过 7 项包装行为测试（`python -B -m unittest discover -s 03_analysis/r3_lfsr_20261003/probes -p test_run_probe.py -v`）：固定 helper/计数、损坏 helper 拒绝、有效控制后才执行候选、负对照编译错不得通过、候选展开错不得归因、候选通过可报告阴性、独立整数 oracle 的 31 非零状态周期。它们没有运行 EDA，不证明 Verilog 控制通过。

所有原始输入、代码、控制和文档哈希见 ASSETS.json。新增输入应在 Git 中按原始字节存储（`-text -whitespace`），不因换行归一化改变题面/候选哈希。
