# 历史开发用 Dockerfile（2026-09-01），对应的是旧的单文件 agent.py 与 CPU llama.cpp 运行时。
# 提交方案包使用的是 submission/Dockerfile（基于赛事方官方基础镜像、符合官方包结构）。
# 本文件保留仅为记录当时的本地 CPU 镜像验证过程，不要用于提交。
ARG BASE_IMAGE=amd-rtl-local/ubuntu:22.04
FROM ${BASE_IMAGE}

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       bash ca-certificates libgomp1 python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY agent.py vivado_eval.tcl run.sh run_baseline.sh serve.sh ./
COPY skill ./skill
COPY model ./model
COPY runtime/llama /opt/llama

ENV PATH="/opt/llama:${PATH}" \
    LD_LIBRARY_PATH="/opt/llama"

RUN chmod +x run.sh run_baseline.sh serve.sh agent.py /opt/llama/llama-server \
    && llama-server --version
ENTRYPOINT ["python3", "/workspace/agent.py"]
CMD ["--help"]
