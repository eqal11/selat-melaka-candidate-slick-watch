FROM python:3.11.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 APP_DATA_DIR=/app/var
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.8.15 && uv sync --frozen --no-dev --no-install-project
COPY api ./api
COPY core ./core
COPY data ./data
COPY validation/cases.yaml ./validation/cases.yaml
RUN uv sync --frozen --no-dev && useradd --create-home --uid 1000 app && mkdir -p /app/var && chown -R app:app /app
USER app
# Check the native runtime and application as the runtime user before publishing the image.
RUN OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 /app/.venv/bin/python -c "import rasterio; from api.main import app; print(app.title)"
EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn","api.main:app","--host","0.0.0.0","--port","8000"]
