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
# Named volumes (app_logs, storage_data in docker-compose.yml) mount
# over these paths on first run and inherit whatever ownership exists
# here at that moment -- create them now, owned by appuser, since the
# process runs as appuser (not root) below and would otherwise get
# PermissionError writing its own log file.
RUN mkdir -p /app/logs /app/data/storage && chown -R appuser:appuser /app/logs /app/data/storage
# alembic.ini's script_location (src/logand_backend/db/migrations) is
# relative to the CWD alembic is invoked from -- this was previously
# missing entirely from the image, so `alembic upgrade head` had nothing
# to run against even if invoked (no docker-compose/CI stack actually ran
# migrations before this, meaning the deployed/CI stack's tables never
# got created at all -- a real, previously-uncaught gap in "the full
# stack actually works end to end").
COPY alembic.ini ./
ENV PATH="/app/.venv/bin:${PATH}"

# Baked in at image-build time (deploy.yml passes --build-arg
# GIT_COMMIT=${{ github.sha }}) since the built image has no .git
# directory to introspect at runtime -- api/admin_version.py reads this
# env var to answer "what commit is actually running right now,"
# distinct from `version` in pyproject.toml (the app's own semver,
# bumped manually/rarely) and distinct from any dependency's own
# version (read live via importlib.metadata at request time, not baked
# in -- always reflects what's ACTUALLY installed in this image, not
# what pyproject.toml asked for, which can differ after a lockfile
# update this ARG wasn't rebuilt for).
ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT}

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
