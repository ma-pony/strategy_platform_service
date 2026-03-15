.PHONY: install run test test-all lint format typecheck check pre-commit-install \
       docker-up docker-down docker-build migrate seed

install:
	uv sync

run:
	uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

test:
	uv run pytest --tb=short

test-all:
	uv run pytest --tb=short -m "" --cov-report=html

lint:
	uv run ruff check src/ tests/

format:
	uv run ruff format src/ tests/

typecheck:
	uv run mypy src/

check: lint typecheck test

pre-commit-install:
	uv run pre-commit install

# Database
migrate:
	uv run alembic upgrade head

seed:
	uv run python -m src.freqtrade_bridge.seeds.seed_strategies

seed-all:
	uv run python -m src.freqtrade_bridge.seeds.seed_all

# Docker
docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f
