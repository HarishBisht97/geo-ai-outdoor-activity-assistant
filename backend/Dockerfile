# syntax=docker/dockerfile:1.6
# Backend image for the Hugging Face Docker Space (CPU Basic) - FastAPI + llama.cpp + baked GGUF weights.

ARG PYTHON_IMAGE=python:3.12-slim

# --- 1. Build llama-cpp-python as a portable CPU wheel ------------------------------------------
FROM ${PYTHON_IMAGE} AS builder
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake git \
    && rm -rf /var/lib/apt/lists/*
# GGML_NATIVE=OFF: the build machine may differ from the runtime CPU (avoids illegal-instruction crashes).
ENV CMAKE_ARGS="-DGGML_NATIVE=OFF -DGGML_AVX=ON -DGGML_AVX2=ON -DGGML_FMA=ON -DGGML_F16C=ON -DGGML_BLAS=OFF"
COPY requirements-slm.txt /tmp/requirements-slm.txt
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r /tmp/requirements-slm.txt

# --- 2. Download the pinned GGUF at build time so restarts never re-download ---------------------
FROM ${PYTHON_IMAGE} AS model
ARG MODEL_REPO=unsloth/Qwen3-1.7B-GGUF
ARG MODEL_REVISION=main
ARG MODEL_FILE=Qwen3-1.7B-Q4_K_M.gguf
RUN pip install --no-cache-dir "huggingface_hub>=0.24"
RUN python -c "from huggingface_hub import hf_hub_download as d; \
d(repo_id='${MODEL_REPO}', filename='${MODEL_FILE}', revision='${MODEL_REVISION}', local_dir='/models')" \
    && ls -la /models

# --- 3. Runtime ----------------------------------------------------------------------------------
FROM ${PYTHON_IMAGE}
ARG MODEL_REPO=unsloth/Qwen3-1.7B-GGUF
ARG MODEL_REVISION=main
ARG MODEL_FILE=Qwen3-1.7B-Q4_K_M.gguf
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 user
WORKDIR /home/user/app

COPY requirements.txt ./
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir -r requirements.txt /wheels/*.whl && rm -rf /wheels
COPY --from=model --chown=user /models /models
COPY --chown=user app ./app
COPY --chown=user static ./static

USER user
ENV PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    MODEL_REPO=${MODEL_REPO} \
    MODEL_REVISION=${MODEL_REVISION} \
    MODEL_FILE=${MODEL_FILE} \
    MODEL_PATH=/models/${MODEL_FILE} \
    N_THREADS=2 \
    N_CTX=4096

EXPOSE 7860
HEALTHCHECK --interval=60s --timeout=5s --start-period=120s CMD curl -fsS http://localhost:7860/health || exit 1
# One worker: each worker would load its own copy of the model.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1", "--timeout-keep-alive", "120"]
