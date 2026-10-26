FROM python:3.11.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.8.15 && uv sync --frozen --no-dev --no-install-project
COPY api ./api
COPY core ./core
COPY data ./data
RUN uv sync --frozen --no-dev && useradd --create-home --uid 10001 app && mkdir -p /app/var && chown -R app:app /app
USER app
EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn","api.main:app","--host","0.0.0.0","--port","8000"]
