# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/opspilot-venv

WORKDIR /app

RUN pip install --no-cache-dir uv \
    && useradd --create-home --user-group --uid 10001 app

COPY --chown=app:app pyproject.toml uv.lock readme.md alembic.ini ./
COPY --chown=app:app src ./src
COPY --chown=app:app configs ./configs
COPY --chown=app:app knowledge_base ./knowledge_base
COPY --chown=app:app evals ./evals
COPY --chown=app:app docker ./docker

RUN mkdir -p \
      /app/data \
      /app/evals/reports \
      /app/knowledge_base/generated \
      /home/app/.cache/huggingface \
    && chown -R app:app /app/data /app/evals/reports \
      /app/knowledge_base/generated /home/app/.cache

FROM base AS simulator

RUN uv sync --frozen --no-dev

ENV PATH="/opt/opspilot-venv/bin:${PATH}"
USER app

CMD ["uvicorn", "opspilot.simulator.services.orders.app:app", "--host", "0.0.0.0", "--port", "8001"]

FROM base AS app

RUN uv sync --frozen --no-dev --extra ml --extra rag --extra agents

ENV PATH="/opt/opspilot-venv/bin:${PATH}" \
    HF_HOME=/home/app/.cache/huggingface

USER app

CMD ["uvicorn", "opspilot.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS dashboard

RUN uv sync --frozen --no-dev --extra dashboard

ENV PATH="/opt/opspilot-venv/bin:${PATH}"

USER app

CMD ["streamlit", "run", "src/opspilot/dashboard/app.py", "--server.address", "0.0.0.0", "--server.port", "8501"]
