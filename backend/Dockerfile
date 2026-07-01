FROM python:3.12-slim AS build

RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml ./
COPY src/ ./src/
RUN uv sync --frozen --no-dev || uv sync --no-dev

FROM python:3.12-slim

RUN useradd --create-home --shell /bin/false appuser
WORKDIR /app
COPY --from=build /app /app
# alembic.ini's script_location (src/logand_backend/db/migrations) is
# relative to the CWD alembic is invoked from -- this was previously
# missing entirely from the image, so `alembic upgrade head` had nothing
# to run against even if invoked (no docker-compose/CI stack actually ran
# migrations before this, meaning the deployed/CI stack's tables never
# got created at all -- a real, previously-uncaught gap in "the full
# stack actually works end to end").
COPY alembic.ini ./
ENV PATH="/app/.venv/bin:${PATH}"
USER appuser

EXPOSE 8000
# Migrate THEN serve, every container start -- idempotent (alembic no-ops
# once the DB is already at head), and means a fresh docker-compose stack
# (test or real) never needs a separate manual/CI migration step someone
# could forget to run before the app's first request.
CMD ["sh", "-c", "alembic upgrade head && uvicorn logand_backend.asgi:app --host 0.0.0.0 --port 8000"]
