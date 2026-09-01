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
