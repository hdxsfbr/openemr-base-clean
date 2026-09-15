# AgentForge Clinical Co-Pilot agent service.
# Holds the model key and delegation secret as file secrets; no database
# credentials, no OpenEMR session (ADR-0003).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin copilot \
    && mkdir -p /app /var/lib/copilot \
    && chown copilot:copilot /var/lib/copilot

WORKDIR /app
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install .

USER copilot
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
