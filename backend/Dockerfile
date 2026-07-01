FROM python:3.12-slim AS build

RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml ./
COPY src/ ./src/
RUN uv sync --frozen --no-dev || uv sync --no-dev

FROM python:3.12-slim

# LaTeX toolchain for professional invoice PDFs (see
# domain/invoices/pdf/renderer.py's doc comment for why LaTeX over a
# pure-Python PDF library) -- latexmk drives the compile, the three
# texlive-* packages cover logandinvoice.cls's own \RequirePackage list
# (geometry, xcolor, tabularx, booktabs, hyperref, fancyhdr, lmodern).
# This is a genuinely large image layer (order of ~1GB) -- an accepted
# tradeoff for PDF output quality the user explicitly asked to look "as
# professional as possible," not an oversight.
RUN apt-get update && apt-get install -y --no-install-recommends \
    latexmk \
    texlive-latex-recommended \
    texlive-latex-extra \
    texlive-fonts-recommended \
    && rm -rf /var/lib/apt/lists/*

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
# could forget to run before the app's first request. This makes
# docker-compose.yml's own one-shot `migrate` profile (still invoked
# explicitly by .github/workflows/deploy.yml before restarting `backend`)
# belt-and-suspenders rather than the only path -- both are safe to run
# together since alembic upgrade head is idempotent; deploy.yml's explicit
# step is kept so a migration failure surfaces as its own clearly-labeled
# deploy step instead of buried in backend's own startup log.
CMD ["sh", "-c", "alembic upgrade head && uvicorn logand_backend.asgi:app --host 0.0.0.0 --port 8000"]
