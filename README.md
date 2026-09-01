# 2026 FPGA 创新设计赛道项目资料库

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

团队已于 2026-08-22 完成报名：

- 厂商：高云半导体
- 平台：高云-J280 姿态控制系统竞赛套件
- 开发方向：基于 FPGA 的实时姿态控制系统
- 作品名称：凌衡实时姿态控制系统
- 团队编号：45561

此前的安路/易灵思推荐保留为历史分析，不再是当前执行方向。报名事实与方案边界见 [`DECISIONS.md`](DECISIONS.md)。

## 当前开发

用户于 2026-09-01 另行授权开发 AMD 题目一的 RTL 本地智能体。代码、容器、模型声明和测试位于 [`04_project/amd_rtl_agent`](04_project/amd_rtl_agent/README.md)。这项开发授权不自动证明官网报名已切换；两种状态在 `PROJECT_STATE.json` 中分开保存。

## 公开仓库边界

Git 仓库只上传可复现源码、脚本、文档、公开赛题资料和必要验证报告。以下内容继续保留在本机原路径，不删除也不上传：4.68 GB 模型权重、生成输出与缓存、AMD 认证日志、群聊原文、我方报名截图和其他队伍截图。模型下载来源、固定版本、字节数和 SHA-256 记录在 `04_project/amd_rtl_agent/model/MODEL.md`。
