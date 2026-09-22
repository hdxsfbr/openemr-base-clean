# AgentForge Clinical Co-Pilot agent service.
# Holds the model key and delegation secret as file secrets; no database
# credentials, no OpenEMR session (ADR-0003).
FROM python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/model-cache \
    HF_HUB_DISABLE_TELEMETRY=1

ARG CACHE_GUIDELINE_MODELS=0
ARG POPPLER_VERSION=25.03.0-5+deb13u4
ARG TESSERACT_VERSION=5.5.0-1+b1
ARG TESSERACT_ENG_VERSION=1:4.1.0-2

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        poppler-utils=${POPPLER_VERSION} \
        tesseract-ocr=${TESSERACT_VERSION} \
        tesseract-ocr-eng=${TESSERACT_ENG_VERSION} \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin copilot \
    && mkdir -p /app /var/lib/copilot \
    && chown copilot:copilot /var/lib/copilot

WORKDIR /app
# Exact versions first (requirements.lock, generated from the running container), then the
# package itself with --no-deps so no runtime dependency can resolve newer on a rebuild with
# --pull. The build backend (setuptools>=69 in pyproject.toml) is not in the lock: pip freeze
# omits it and pip's isolated build environment fetches it fresh at image build time.
COPY requirements.lock ./
RUN pip install -r requirements.lock
COPY pyproject.toml README.md ./
COPY app ./app
COPY guideline-corpus ./guideline-corpus
RUN pip install --no-deps .
RUN mkdir -p /app/model-cache \
    && if [ "$CACHE_GUIDELINE_MODELS" = "1" ]; then python -m app.cache_guideline_models; fi \
    && chown -R copilot:copilot /app/model-cache /app/guideline-corpus

USER copilot
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
