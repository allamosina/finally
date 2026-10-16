# syntax=docker/dockerfile:1
# FinAlly: multi-stage build. Node builds the static frontend, Python serves everything on :8000.

# ---- Stage 1: frontend static export ----
FROM node:20-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY frontend/ ./
RUN npm run build
# Next.js `output: 'export'` writes the site to /frontend/out

# ---- Stage 2: Python runtime ----
FROM python:3.12-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    STATIC_DIR=/app/static \
    FINALLY_DB_PATH=/app/db/finally.db

# Backend lives in /app/backend so the bind mount at /app/db cannot shadow backend/db/ (schema.sql, seed.json)
WORKDIR /app/backend

# Dependencies first for layer caching
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application code and the built frontend
COPY backend/ ./
COPY --from=frontend-build /frontend/out /app/static

# /app/db is the bind-mount target for the SQLite file
RUN mkdir -p /app/db
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
