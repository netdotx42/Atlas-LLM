FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    ATLAS_DATA_DIR=/data

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

WORKDIR /app
RUN useradd --create-home --uid 10001 atlas
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY ui/dist ./ui/dist
RUN uv sync --no-dev --no-editable \
    && chown -R atlas:atlas /app \
    && mkdir -p /data \
    && chown atlas:atlas /data

USER atlas
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "atlas.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
