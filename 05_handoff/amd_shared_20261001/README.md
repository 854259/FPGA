# AMD 双人共用实例交接（2026-10-01）

下一步由队友操作。本次只同步资料与脚本，没有启动新服务器。

## 先看结论

- 旧 AMD 实例已销毁；旧 Jupyter 地址不可作为新实例连接信息。
- Linux Vivado 精简包已在原电脑生成，902 个组件逐个 MD5 校验通过，压缩组件及安装器合计约 26.37 GB。原始包仍保留。
- 100 GiB 空工作区在预算上有条件可行，实际安装峰值未测。100 GB 十进制不满足目前保守门槛。先安装验证 Vivado，再删除云端安装暂存，最后下载模型。
- 云端 Vivado、许可证、仿真/综合尚未验证；不能直接宣布可以全量跑分。
- 服务器将由两名同学共用。各自账号和公钥、独立结果目录，Vivado/模型/题库共享一份，单卡评测排队。不要重复下载或同时启动两份模型服务。

## 接手前需要的材料

1. 平台账号拥有者创建具备 SSH 的正确 GPU 实例，并提供实际 SSH 地址及端口。当前目标记录为验证 W7900/gfx1100、决赛 R9700/gfx1201，按单卡 32 GB 设计；旧卡仅确认 gfx1100/47.98 GiB，不能据此认定型号。先核对再选择实例。
2. 队友生成自己的 SSH 密钥，只提供 `.pub` 公钥用于账号配置；私钥保留在本人电脑。
3. 准备适用于实际安装主机和目标器件的 Vivado 2026.1 许可证，取得后通过实际仿真/综合验证。许可证文件不放 GitHub。
4. 从原电脑取得下方精简包，或由原电脑直接流式上传。GitHub 不包含安装器、模型权重和完整离线包。

## 本机安装包

精简包位置：

```text
E:\26qiansai\AMD-test-20260930\Vivado-2026.1-Linux-ZynqMP-minimal.tar
```

- 大小：26,371,880,960 字节。
- SHA-256：`dae39976c08a6ef559a25306cc8005616f2952c60ec03183f250772b7ba92708`。
- 原始包：`E:\26qiansai\FPGAs_AdaptiveSoCs_Unified_SDI_2026.1_0616_1700.tar`，105,522,216,960 字节，MD5 `b577835d4304f07e40292c51a4018482`，与官网下载页一致。

转移精简包后先校验 SHA-256。不要把完整 105.52 GB 包传到 100 GB 云盘，也不要用普通上传再解包的方式保留两份精简包。

## 操作顺序

先阅读 [100GB 部署方案](100GB部署方案.md)。在本目录运行上传脚本；机器需有 Python 和 SSH 客户端，先正常连接并核验实例主机身份。替换下方主机和端口为新实例实际值：

```powershell
python .\stream_upload_installer.py "E:\26qiansai\AMD-test-20260930\Vivado-2026.1-Linux-ZynqMP-minimal.tar" --host 用户名@实际主机 --port 实际端口
```

此脚本会先检查空闲空间，然后把 TAR 流直接解到新目录 `/workspace/vivado-offline-stage`，不在云端另存 TAR。目录已存在或空间不足即停止；失败后先检查部分上传文件，不要反复叠加上传。

上传完成后，在 Linux 运行：

```bash
stage=/workspace/vivado-offline-stage
installer="$stage/FPGAs_AdaptiveSoCs_Unified_SDI_2026.1_0616_1700"
python3 "$stage/deployment/preflight_linux_space.py" "$installer" \
  --bom "$stage/deployment/linux-vivado-bom.json"
```

预检需出现 `PAYLOAD_AND_SPACE_PREFLIGHT_PASS`。随后查看原安装器 `"$installer/xsetup" --help`，用包内 `deployment/vivado-linux-minimal-config.txt` 执行原厂批量安装流程；安装路径 `/workspace/AMD`，只选 Zynq UltraScale+ MPSoCs 及必选依赖。按安装器提示处理协议、系统依赖和许可证。临时文件也放在工作区并监测空间。

确认版本、xczu3eg-sbva484 器件、仿真与综合全部正常并备份日志后，才清理这次云端安装暂存目录。保留安装好的工具，以及本机离线包。然后下载一份 Qwen3.6-27B Q4_K_M（约 19.1 GB），复用镜像已有环境，先冒烟再全量。每人使用不同结果目录；运行前至少保留 8 GiB，空间不足先停止，不能删除队友文件。

## 已有测试，避免重复或误报

- AMD Qwen3.6-27B Q4_K_M 已在旧实例实际 GPU 加载过；6 题 Icarus 冒烟 baseline 5/6、agent 6/6。
- AMD baseline 156/156 候选生成完成，非空 124、Icarus 编译 110、功能诊断 97。32 个空输出仍计入分母。
- 这些不是 Vivado 官方 L3 成绩；AMD 全量 agent 配对评测未完成。
- 旧基准备份位于原电脑 `E:\26qiansai\AMD-test-20260930\Qwen36-baseline156-20260930.tar.gz`，SHA-256 `f9e48e9cda0d5c0999b612ec23dc6d1c4dcb477ec43a927e1e6969c96786e6a6`。
- 冒烟备份为同目录 `Qwen36-AMD-20260930-smoke-evidence.tar.gz`，SHA-256 `63b3db2641090658da980c790a83bde0ae53e7e82f452dd87c67420091a0b055`。备份未随本次交接公开上传，需要复用候选时向原电脑取得。

完成安装后记录实际磁盘占用、GPU 型号、软件版本和许可证验证结果，再更新项目状态。不要把预算推算改写成已经验证。
