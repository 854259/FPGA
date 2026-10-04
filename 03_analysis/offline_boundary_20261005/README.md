# 当前实例的隔离网络能力实测

2026-10-05 06:10北京时间，capture.py在自己新建的进程组执行一次 `unshare --user --map-root-user --net`。返回码1，stderr为 `unshare: unshare failed: Operation not permitted`，新网络namespace未创建。已确认自有探测进程组消失、父进程网络namespace不变；0模型/EDA，未改宿主路由、防火墙、服务或实例。

VERIFIED_CAPABILITY_SNAPSHOT.json绑定实际capture.py SHA a1b4a01011de044cb1a90ef876c1f329b29182e68e5e49eab10fc6c7152ec158、完整argv/返回值及自有清理结果。初次内联探测保留CAPABILITY_SNAPSHOT.json，没有覆盖旧证据。现场未找到docker/podman/ip/strace；工具路径查找只说明本实例当时状态。

结论：当前实例不能用已测试的user+network namespace组合完成操作系统层面的网络隔离验收。程序使用回环模型端口、纯标准库、模拟模型测试通过，均不能替代完整模型/EDA/接口的断网证书；其他隔离方法和可构建环境尚未测试，不推断所有环境均不支持。

复验命令：把同一capture.py复制到有隔离权限的验证环境，运行 `python3 -B capture.py`，先确认isolated_namespace_created=true及父namespace不变，再在独立环境装载已冻结模型/智能体/原工具链进行断网真实求解、异常恢复、正式接口与五样本验收。模型权重/依赖需预先在本地；基础镜像tag/digest须核验，现有Dockerfile仍有占位tag。此探测自身即使创建namespace成功，也不算完成模型或目标单卡32GB断网验收。

当前仍优先完成票25全量审计及已排队原生/桥接验证；不停止/重启共享模型来做隔离测试，不改变队友任务，goal active。目标R9700单卡32GB/峰值、正式镜像构建和真实五样本仍待验收。

06:13现场复查：全量293/312、310请求、complete=false、error=null，guard未终态；模型2013333/start823869819及评测3390465/start841229941实际身份仍有效。一次SSH观察建连超时后复查同PID成功，不据此重跑或终止任务。完整分仍待终态审计。
