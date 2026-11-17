FROM python:3.12-slim AS builder
WORKDIR /app/backend
RUN pip install --no-cache-dir uv==0.13.8
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/backend/.venv/bin:$PATH"
RUN groupadd --gid 10001 cloudpilot && useradd --uid 10001 --gid cloudpilot --no-create-home cloudpilot
WORKDIR /app/backend
COPY --from=builder /app/backend/.venv ./.venv
COPY backend/alembic.ini ./alembic.ini
COPY backend/alembic ./alembic
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=3)"
CMD ["uvicorn", "cloudpilot.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
