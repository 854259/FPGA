# VerilogEval v2 固定信息

- 官方仓库：`https://github.com/NVlabs/verilog-eval`
- 本地目录：`bench/verilog-eval`（被 `.gitignore` 排除，需单独获取）
- 固定 commit：`c498220d0a52248f8e3fdffe279075215bde2da6`
- 使用数据：`dataset_spec-to-rtl`
- 三元组数量：156 组 `_prompt.txt`、`_ref.sv`、`_test.sv`
- 首轮烟测：`Prob001_zero`、`Prob017_mux2to1v`、`Prob031_dff`

边界：模型只接收 `_prompt.txt`。`_ref.sv` 与 `_test.sv` 只能交给本地评测器，禁止进入生成或修复提示词。官方仓库默认评测实现不等于 AMD 赛题判定；本项目统一使用 Vivado 2025.2 的 `xvlog`、`xelab`、`xsim` 和指定器件综合。

重新获取：

```powershell
git clone https://github.com/NVlabs/verilog-eval.git .\bench\verilog-eval
git -C .\bench\verilog-eval checkout c498220d0a52248f8e3fdffe279075215bde2da6
```
