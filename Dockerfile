FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /build/
RUN pip install --no-cache-dir -e /build

COPY gateflow /build/gateflow

# Production image
FROM python:3.12-slim

RUN groupadd -r gateflow && useradd -r -g gateflow gateflow

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /build/gateflow /app/gateflow

RUN chown -R gateflow:gateflow /app
USER gateflow

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

CMD ["python", "-m", "gateflow"]
