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
ENV PATH="/app/.venv/bin:${PATH}"
USER appuser

EXPOSE 8000
CMD ["uvicorn", "logand_backend.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
