# AI backend: FastAPI + LangGraph. Runs as a non-root user; config comes from env + config/.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10
WORKDIR /app

# Dependencies first (cached until pyproject.toml changes), then the code.
COPY pyproject.toml README.md ./
RUN mkdir -p src/ai_backend && touch src/ai_backend/__init__.py \
    && pip install . && pip uninstall -y ai-backend
COPY src ./src
RUN pip install --no-deps .
COPY config ./config

RUN useradd --create-home --uid 10001 app
USER app
EXPOSE 8000
# Healthy only when config, models, the bank and storage all check out (/v1/health → 200).
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/v1/health', timeout=4)"
CMD ["uvicorn", "ai_backend.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
