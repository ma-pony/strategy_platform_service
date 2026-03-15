.PHONY: install run test lint format typecheck check pre-commit-install

install:
	uv sync

run:
	uv run python -m src.main

test:
	uv run pytest --tb=short

lint:
	uv run ruff check src/ tests/

format:
	uv run ruff format src/ tests/

typecheck:
	uv run mypy src/

check: lint typecheck

pre-commit-install:
	uv run pre-commit install
