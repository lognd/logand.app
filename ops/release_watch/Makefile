.PHONY: install test lint typecheck check fmt

install:
	uv sync

test:
	uv run pytest tests/ -n auto

lint:
	uv run ruff check src/ tests/

fmt:
	uv run ruff format src/ tests/

typecheck:
	uv run ty check src/

check: lint typecheck test
