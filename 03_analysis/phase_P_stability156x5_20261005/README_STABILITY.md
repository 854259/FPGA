# 已验证 phaseP 的156×5开发稳定性复测草稿

仅准备，0实际模型/EDA/SSH/FIFO/Git，未冻结。根任务冻结入口是 prepare_stability.py，阶段入口 stability_stage.py，终态只读审计 stability_audit.py；原复制 prepare.py/pilot stage/audit 均保留旧44字节但不作为新阶段入口。原 pilot.py 的 judge 子命令仍作为唯一原判定入口。

只使用已验证最新 phase_full156 的 P：44源逐SHA复制，原8192 token、一次repair、绝对300秒、原机械修补/phase功能反馈/抽取/skills/native judge保持。不加bit、semantic、diagnostic优先级、driver/xelab候选等因素。已有功能检查和官方判定原生xelab仍存在。

一整项FIFO，5轮独立fresh，每轮156题顺序固定，共780样本/max1560请求。所有失败保留，独立目录P/repeat-i/task，不重抽、删题或挑最好。原worker调用日志event_id会跨重复冲突；新小wrapper仅在台账ID和记录中附repeat，模型payload及原worker字节保持。

12小时stage cap43200秒，guard43400秒，整任务735分钟租约；不是预计时长。若未跑满780，保存partial failure，不冒充5轮完成。原每样本求解300、judge内部300/外层360均保持。

终态按全部780实际请求、首/修复、原生回执、真实官方判定重建每轮与总体加权均值/等级和每题5个等级。不用bestof选择，不称赛事隐藏/正式五样本资格、独立验证、部署或新增增分。实际capture只绑定捕获时已有源；根任务必须在准入另核随后semantic新组，不能声称旧12组445已经含它。

guard_wrapper/collector/evaluator/deps原字节保持。source保护按显式local/cloud root动态集合；原始日志与收据保留私有。当前草稿的FAKE检查只验证索引、分母、均值、日志ID、原源身份及边界，不是780真实运行证据。
