.PHONY: install test test-system lint typecheck check fmt clean bump migrate

install:
	uv sync

test:
	uv run pytest tests/unit tests/integration -n auto

test-system:
	uv run pytest tests/system -n auto

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

bump:
	uv run python scripts/bump_version.py

clean:
	rm -rf dist/ build/ .venv/ __pycache__ .pytest_cache .ruff_cache
