# 正式接口五样本预检工具

26项源资产冻结（TOOLS_SPEC SHA cd668071ad7d30cb97b030c82ec04b683da16c66077cd9d513f238818b8802fc），本机/Linux各7项纯检查通过。含固定生产HTTP Handler的30次假求解、产物/trace字节绑定、五次平均、不完整/错误顺序/工具错误拒绝、未返回记录、原技能与预算/事实篡改拒绝、真实CPython观察钩子保留UTF-8请求字节、真实阶段前置证据门槛。0真实模型/EDA；未生成五份实际样本，未创建RUN_SPEC/未提交FIFO。

计划范围：112优先选择、115算术右移、122不支持新规则的正确稿控制；每题/模式5次新HTTP请求，共30份样本。baseline原版与candidate固定相同模型、8192token、温度0、300秒；baseline一次调用/零工具，agent原一次修复。至多45实际模型POST、外判每份最多300秒；不重抽择优，统计全部五次均值。不是完整156题五样本、独立自然题或国一证据。

候选生产package17文件与已冻结v2逐字节一致；无新增代理、传输/响应/模型体改写。只在评测worker的PYTHONPATH注入独立sitecustomize，通过CPython urllib.Request审计事件观察模型POST体；不记录认证头。观察点在网络前，属于尝试计数，收到回复需配合原worker trace；未捕获原始模型回复，不能宣称完整回复内容链。parent只复制自己的临时worker产物，外判在HTTP/模型输入之外，参考/TB不进入模型。

健康检查使用真实原model端口、submission配置；瞬时开发卡<=32GiB不是目标R9700硬件容量、峰值或断网证书。服务在自有临时loopback端口，通过原HTTP /v1/health和/v1/solve，不替换现有正式部署。

执行前必须：原312份回归完整审计与归因门槛通过、票30/31真实原生/健康终态及guard成功、二者完整只读审计actual_execution_verified=true。bind_run.py读这四份真实收据，绑定SHA并冻结新RUN_SPEC，随后打包新运行目录并整任务FIFO提交；不足条件不消耗模型验证被否定候选。

```text
python -B bind_run.py --v1 V1_ACTUAL_AUDIT.json --v2 V2_ACTUAL_AUDIT.json --full156 FULL_AUDIT.json --attribution ACTUAL_DECISION.json
```

bind仅准备文件，不发模型请求、不提交队列。测试合成数据不能作为真实前置证据。实际接入/五样本结果仍须终态只读审计，不能仅凭summary.passed验收。

06:02北京时间全量288/312、304请求、complete=false、error=null，模型及评测实际PID/start保持，30/49/51/28/34冻结源保持；新预检工具Linux验证不占模型队列。旧A0.7692/C0.7641仍为已审计旧结果，当前不发布部分新分。G3完整净收益/G4独立/G5五样本镜像断网目标硬件验收仍未完成。
