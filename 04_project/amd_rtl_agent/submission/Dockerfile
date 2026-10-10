# 基于赛事方官方基础镜像构建。基础镜像自带 ROCm、Vivado / Vitis 与目标架构可用的推理栈，
# 自己重建这些没有分数收益。
#
# 官方计划两个变体：gfx1100（验证窗口，W7900）与 gfx1201（决赛，R9700）。两代架构的
# 预编译内核与 wheel 不通用，必须选定的那一个。
#
# ★ 下面的标签是占位符。正式镜像名由赛事方在验证窗口前公布；在那之前只有显式传入名字
#   才能构建成功：
#
#     docker build --build-arg BASE_IMAGE=<公布的名字> -t 45561-agent .
#
ARG BASE_IMAGE=fpgachina2026/base-gfx1100:REPLACE_WITH_ANNOUNCED_TAG
FROM ${BASE_IMAGE}

# --- 沙箱断网，一切都必须在构建期烤进来 ---------------------------------------

WORKDIR /opt/agent

# 本方案的智能体是纯标准库实现（agent/runtime.py 只用 Python 标准库），因此不需要
# 安装任何第三方包。这是一项刻意的设计：依赖越少，断网构建与复现的失败面越小。
# 若将来确实引入依赖，在此处恢复 requirements 安装：
#   COPY requirements.txt .
#   RUN pip3 install --no-cache-dir -r requirements.txt

COPY agent/   agent/
COPY skill/   skill/
COPY serve/   serve/
COPY model/   model/
COPY run.sh run_baseline.sh baseline.py upstream.json LICENSE.official ./
COPY manifest.json REPORT.md ./

RUN chmod +x run.sh run_baseline.sh serve/llama.sh

# 模型权重必须在断网前落到本地磁盘：沙箱里启动时下载会失败。
# 两种做法二选一：
#   1) 构建期拷入（镜像会很大）：
#        COPY models/ /opt/models/
#   2) 运行期挂载：
#        docker run -v /宿主/模型目录:/opt/models ...
# COPY models/ /opt/models/

# 不要在这里设置 PATH 或 XILINX_* 变量。官方基础镜像已经导出 XILINX_VITIS /
# XILINX_VIVADO 以及工具链 PATH；工具本体在 /tools/Xilinx/2026.1/ 下，而该布局在
# 2026.1 是「版本在前」、在 2024.2 及更早是「工具在前」——这正是接口契约要求
# 「读环境变量、不要自己拼路径」的原因。
#
# 所有 profile 都要求同机回环模型服务。submission 的 health 对已测显存检查上限，
# 显存未知仍可能报告 ready；ready 不证明正式资源/隔离验收。development 仅用于 AMD 开发。
ENV MODEL_PATH=/opt/models/Qwen3.6-27B-Q4_K_M.gguf \
    LLM_BASE_URL=http://127.0.0.1:8000/v1 \
    MODEL_NAME=Qwen3.6-27B-Q4_K_M \
    RTL_PROFILE=submission \
    RTL_REPAIRS=1 \
    RTL_MAX_TOKENS=8192 \
    RTL_TEMPERATURE=0

# 只暴露提交用的 HTTP 口，由平台隧道转发；两个服务都只绑 127.0.0.1。
# 推理服务端口（8000）不要暴露。
EXPOSE 7860

# 刻意不设 ENTRYPOINT：赛事方直接调用 run.sh / run_baseline.sh，
# HTTP 服务在评测日单独启动。
CMD ["/bin/bash"]
