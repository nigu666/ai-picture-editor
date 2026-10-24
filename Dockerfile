FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim-bookworm AS dependencies
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1
RUN pip install --no-cache-dir uv==0.13.1
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --all-extras --no-dev --no-install-project

FROM python:3.13-slim-bookworm AS runtime
LABEL org.opencontainers.image.source="https://github.com/nigu666/ai-picture-editor" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="v0.1.0"
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates libgl1 libglib2.0-0 libgomp1 libpq5 fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser
ENV PATH=/app/backend/.venv/bin:$PATH \
    PYTHONPATH=/app/backend PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    TEXT_FONT_PATH=/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc \
    MATTING_MODEL_PATH=/models/u2netp/u2netp.onnx \
    SAM_MODEL_DIR=/models/sam LAMA_MODEL_PATH=/models/lama/lama_fp32.onnx
WORKDIR /app/backend
COPY --from=dependencies /app/backend/.venv /app/backend/.venv
COPY backend/app/ ./app/
COPY backend/alembic.ini ./alembic.ini
COPY backend/migrations/ ./migrations/
COPY LICENSE NOTICE /app/
COPY --from=frontend /build/dist /app/frontend/dist
USER 10001:10001
EXPOSE 7302
STOPSIGNAL SIGTERM
ENTRYPOINT ["python", "-m", "app.deployment"]
CMD ["api"]
