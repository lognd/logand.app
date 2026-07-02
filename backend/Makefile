.PHONY: install test test-system coverage lint typecheck check fmt clean bump migrate healthcheck

install:
	uv sync

test:
	uv run pytest tests/unit tests/integration -n auto

test-system:
	uv run pytest tests/system -n auto

# Includes tests/system -- run locally for the real number; in CI, the
# unit+integration-only `backend` job's coverage always undercounts the
# LaTeX-dependent PDF paths (see tests/system/test_invoice_pdf_generation.py's
# skip condition -- latexmk isn't installed on that runner, only inside
# the real Docker image the system-tests job builds).
coverage:
	uv run pytest tests/unit tests/integration tests/system --cov --cov-report=term-missing -n auto

test-fast:
	uv run pytest tests/unit tests/integration --testmon

lint:
	uv run ruff check src/ tests/

fmt:
	uv run ruff format src/ tests/

typecheck:
	uv run ty check src/

check: lint typecheck test
	uv run frob check src/

migrate:
	uv run alembic upgrade head

# Checks every real subsystem/dependency (DB, redis, Stripe, PayPal,
# SMTP, storage backend, latexmk, backups, public reachability) against
# whatever backend/.env currently points at -- see docs/usage.md's
# health-check section. --skip-http since a local `make healthcheck`
# usually isn't run against a live public domain.
healthcheck:
	uv run python -m logand_backend.scripts.health_check --skip-http

bump:
	uv run python scripts/bump_version.py

clean:
	rm -rf dist/ build/ .venv/ __pycache__ .pytest_cache .ruff_cache
