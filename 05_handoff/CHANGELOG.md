# 变更记录

## 2026-09-01

- 归档 AMD 2026 选题指南、团队讨论截图和队伍 45561 完整报名页；重新生成 PDF 文本、元数据和 15 个源文件哈希清单。
- 新增 D-002：按用户授权开发 AMD 题目一 RTL track，同时保留高云 J280 已验证报名事实，不虚构官网改报。
- 安装用户级 Python 3.12.10；在现有 WSL2 中安装并验证 Docker Engine 29.7.2。
- 从 Canonical 官方 OCI rootfs 校验并导入 `amd-rtl-local/ubuntu:22.04`；构建 `amd-rtl-agent:dev`，断网 mock 冒烟通过。
- 将已固定 commit 的最小 CPU llama.cpp runtime 和许可证纳入镜像；最终镜像 `a449bd5e...80841f`（4,645,865,911 字节）在 `--network none` 下通过真实模型 `/health`、最短聊天请求和 mock agent 闭环。
- 实现标准库单文件 RTL agent、严格 baseline、Vivado 编译/仿真/综合入口、有限修复、pass@1/pass@5 和 VerilogEval 接入。
- 固定 VerilogEval v2 commit `c498220d0a52248f8e3fdffe279075215bde2da6`，确认 156 组三元组。
- 编译 CPU `llama-server` commit `010be9683afabe14ce299197b38c329f94bae568`。
- 下载并校验 Qwen2.5-Coder-7B-Instruct Q4_K_M：4,683,073,536 字节，SHA-256 `509287f78cb4d4cf6b3843734733b914b2c158e43e22a7f4bf5e963800894d3c`。
- Python 8 个单元测试通过；Vivado 正负 fixture 验证通过；真实 Qwen CPU 在 3 个无歧义公开题上通过 baseline 与 agent 单样本仿真。
- 识别并记录 VerilogEval 上游数据不一致：`Prob031_dff` 端口方向冲突、`Prob034_dff8` 未声明初值却由参考/测试要求初值；这些失败不伪装为模型错误或成功。
- 修复阶段增加一条通用端口方向矛盾诊断；只根据仿真日志与候选代码判断，不读取参考答案/测试台，不按题号特判。
- 为 Zynq UltraScale+ MPSoC 器件包生成精确增量安装/验证脚本；用户完成 AMD 认证和 UAC 后，首次下载因 CDN SSL/连接超时失败，脚本增加最多 4 次有限重试后安装成功，`xczu3eg-sbva484-1-e` 查询计数为 1。
- `tools/check_environment.ps1` 返回 `ENVIRONMENT_CHECK=PASS`；在 `xczu3eg-sbva484-1-e` 上完成编译/展开/仿真/综合，功能 fixture 为 `Mismatches: 0`，含时钟 fixture 的 5 ns（200 MHz）时序约束全部满足，并生成 DCP、时序和资源报告。
- 修正新 PowerShell 会话可能优先命中 WindowsApps 空 `python.exe` 别名的问题；环境检查现在优先使用已安装的 Python 3.12 实际路径，8 个单元测试复验通过。
- 初始化 Git `main` 分支并发布到公开仓库 `https://github.com/854259/FPGA`；首次导入提交 `ad143eb` 使用 `854259 <3260548169@qq.com>`。上传前排除模型权重、生成缓存、认证日志及含团队/第三方隐私的原始截图和群聊，原文件仍保留在本机。
- 向 GitHub 用户 `nzh152-lang` 发出 `854259/FPGA` 的 Write 协作者邀请；邀请 ID `331205643`，当前状态为等待对方接受。
- ROCm 实测及赛事方尚未发布的官方镜像/隐藏题集/最终接口保持待办，不写成完成。

## 2026-08-22

- 建立项目资料目录和 AI 同步规范。
- 归档 5 份厂商选题指南 PDF。
- 归档 2 张群聊技术截图；核验与 QQ 原图 SHA-256 一致。
- 保存群聊原始摘录。
- 使用 `pypdf` 生成逐页 UTF-8 全文和 PDF 元数据。
- 生成源资料 SHA-256 清单和资源链接索引。
- 完成五家赛题第一轮新手可行性分析。
- 形成短名单：安路选题一、易灵思赛题四、安路选题二。
- 保持最终选题状态为“未决定”。
- 部署 33 个项目文件到 `D:\HUST\IC\FPGA`，相对路径和 SHA-256 全部一致。
- 归档队伍 45561 报名截图。
- 将选题状态更新为：高云 J280“基于 FPGA 的实时姿态控制系统”，作品“凌衡实时姿态控制系统”。
- 新增 `DECISIONS.md`，严格区分报名事实、拟实施方案和未完成工作。
- 归档中科亿海微 2026 FPGA 赛道指南，新增逐页文本、元数据、资源入口与专项摘要。
- 归档 15:38–17:03 群聊补充摘录；将“成员回复 OK”保留为待核验入队状态，将“学数电”记录为计划而非完成。
- 将资料统计更新为 6 份 PDF、11 个原始源文件；高云 J280 的已确认选题和报名状态保持不变。
- 归档外部队伍 46576 的 AMD 报名截图并建立队伍身份边界；资料统计更新为 12 个原始源文件，我方仍为队伍 45561、高云 J280。
