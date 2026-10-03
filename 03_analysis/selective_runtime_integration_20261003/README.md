# 隔离选择性复查原型

这是研究目录，**不是正式提交包**。只改本目录runtime，正式 `04_project/amd_rtl_agent/submission/` 保持原字节；这里没有提交manifest/Docker/守护入口，不能拿来冒充已验收发布包。

阅读 `RESULT.md`、`validation_summary.json`，再看 `LINUX_PREFLIGHT_NEXT.md`。源码差异为 `runtime_delta.patch`；复制源码与测试的冻结清单为 `source_manifest.json`。`local_receipts_attempt1/2/3.json` 是先行失败或证据缺陷的记录，最终证据只用 `local_receipts.json`。

从仓库根运行本地测试：

```text
python -B 03_analysis/selective_runtime_integration_20261003/tests/test_selective_runtime.py
```

设置 `LOCAL_INTEGRATION_RECEIPTS` 为新的绝对输出路径可以导出本次receipt；不覆盖已有冻结证据。测试只启动loopback假模型和受控编译器，Windows使用本轮生成的xvlog.bat，Linux使用受控xvlog脚本。正式模型、Vivado和云端不参与。

原型环境变量为 `RTL_REVIEW_MODE=off/observe/control/checklist`（默认off），可选上限 `RTL_REVIEW_LLM_CAP_S=20`、`RTL_REVIEW_COMPILE_CAP_S=5`、`RTL_REVIEW_CLEANUP_RESERVE_S=6`。这些本轮只做行为验证，真实成本未测。模型客户端超时的服务端取消为unknown；静态候选采用的功能改善为unverified。
