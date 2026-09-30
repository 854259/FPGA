# 2026 FPGA 创新设计赛道项目资料库

## Codex Cloud 与 AMD 服务器

云端环境用于代码阅读、编辑、静态审查和 PR 交付；所有项目代码执行、测试、RTL编译/仿真/综合、Vivado及模型评测都在当前授权 AMD 服务器完成。云端不自动安装依赖、运行测试或启动模型，不保存服务器凭据。AMD验证不可用时明确标记未验证，不在其他主机补跑。规则见 AGENTS.md 顶部。

当前云端配置分支为 codex/fpga-cloud-amd-execution，基于已发布运行分支 fix/rtl-stream-runtime-20260929 的 4223328；不要默认 main 包含最新修复。后续修改按明确提交 SHA 交给 AMD 侧，运行中的冻结实验不自动换版本。本地未提交资料不会随 GitHub 克隆上传。


本目录用于整理 2026 FPGA 赛道指南、团队证据、选题分析和工程实现。

## 进入方式

- AI/代理：先读 [`AGENTS.md`](AGENTS.md)，再读 [`AI_CONTEXT.md`](AI_CONTEXT.md)。
- 团队成员：先读 [`PROJECT_STATUS.md`](PROJECT_STATUS.md) 和 [`03_analysis/00_选题总览与建议.md`](03_analysis/00_选题总览与建议.md)。
- 查原文：先看 [`MATERIALS_INDEX.md`](MATERIALS_INDEX.md)，再进入 `01_sources/` 或 `02_extracted/pdf_text/`。
- 交接任务：读 [`05_handoff/AI_HANDOFF.md`](05_handoff/AI_HANDOFF.md)。

## 目录约定

```text
01_sources/      用户提供的原始资料，只读保存
02_extracted/    PDF 全文、元数据、哈希和资源链接
03_analysis/     选题比较与逐厂商分析，属于分析结论
04_project/      后续硬件、RTL、软件、测试和演示工程
05_handoff/      AI/成员交接和变更记录
tools/           可复现的资料提取与清单脚本
```

## 当前决定

团队最初于 2026-08-22 报名高云 J280，用户于 2026-09-13 明确确认已经改报 AMD。当前决定为：

- 厂商：AMD
- 平台：AMD FPGA 器件
- 开发方向：题目一“RTL/HLS 本地智能体设计赛道”
- 参赛子方向：RTL track（不做 HLS）
- 作品名称：当前对话尚未提供，不作猜测
- 团队编号：45561

高云 J280、安路和易灵思均只保留为历史资料，不再是当前执行方向。报名事实与方案边界见 [`DECISIONS.md`](DECISIONS.md)。

## 当前开发

当前开发即 AMD 题目一 RTL 本地智能体。代码、容器、模型声明和测试位于 [`04_project/amd_rtl_agent`](04_project/amd_rtl_agent/README.md)。

## 公开仓库边界

Git 仓库只上传可复现源码、脚本、文档、公开赛题资料和必要验证报告。以下内容继续保留在本机原路径，不删除也不上传：4.68 GB 模型权重、生成输出与缓存、AMD 认证日志、群聊原文、我方报名截图和其他队伍截图。模型下载来源、固定版本、字节数和 SHA-256 记录在 `04_project/amd_rtl_agent/model/MODEL.md`。
