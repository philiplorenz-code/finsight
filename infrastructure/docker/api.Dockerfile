FROM python:3.12-slim AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY infrastructure/docker/api-requirements.lock /build/requirements.lock
RUN pip install --require-hashes -r /build/requirements.lock
WORKDIR /build/api
COPY apps/api/pyproject.toml ./
COPY apps/api/app ./app
RUN pip install --no-deps .

FROM python:3.12-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    LITELLM_TELEMETRY=False LITELLM_LOCAL_MODEL_COST_MAP=True \
    LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false DO_NOT_TRACK=true
RUN groupadd --gid 10001 finsight && useradd --uid 10001 --gid finsight --no-create-home finsight \
    && mkdir -p /data/imports /data/app /app && chown -R finsight:finsight /data /app
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY --chown=finsight:finsight apps/api/alembic.ini ./
COPY --chown=finsight:finsight apps/api/migrations ./migrations
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]
