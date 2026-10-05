# 当前实例的另一类隔离能力只读查询

2026-10-05北京时间约16:57，在单独的自有Python子进程执行`capability.py`。当前Linux x86_64、kernel 6.8.0-79-generic，从本机已安装UAPI头读取Landlock查询的系统调用编号444；以参数`(NULL, 0, VERSION)`实际返回ABI4/errno0。外层Seccomp查询为模式2，no_new_privs查询为0。

收据`CAPABILITY_RECEIPT.json`绑定源码SHA e19e27bb、头文件SHA、完整参数及返回值；自有子PID3991347/start846429387已退出，父网络namespace与no_new_privs/seccomp状态保持，共享模型完整身份保持。查询没有安装限制策略、创建namespace、发送网络请求或调用模型/EDA。

此结果只证明当前进程可以查询到Landlock ABI4。规则创建、实际文件和执行拒绝、网络过滤、继承与工具兼容尚未测试；不发沙箱或断网证书。此前user+network namespace组合的实际失败仍见`03_analysis/offline_boundary_20261005/README.md`，其范围不扩展到未测方式。

用户随后明确断网验证延后、作对率与分数优先。本目录停留在只读能力查询，不继续实际规则/过滤控制；未来验收再单独按真实证据推进。

接口及查询含义依据[Linux官方Landlock文档](https://docs.kernel.org/userspace-api/landlock.html)；过滤设计依据[Linux官方Seccomp文档](https://www.kernel.org/doc/html/latest/userspace-api/seccomp_filter.html)。当前实测结果以本目录收据为准。
