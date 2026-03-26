.PHONY: install run test test-all lint format typecheck check \
       pre-commit-install pre-commit-run \
       docker-up docker-down docker-build docker-logs \
       migrate seed seed-all

# ---- 开发 ----
install:
	uv sync
	uv run pre-commit install

run:
	uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# ---- 测试 ----
test:
	uv run pytest --tb=short

test-all:
	uv run pytest --tb=short -m "" --cov-report=html

# ---- 代码质量 ----
lint:
	uv run ruff check src/ tests/

format:
	uv run ruff format src/ tests/

typecheck:
	uv run mypy src/

check: lint format-check typecheck test

format-check:
	uv run ruff format --check src/ tests/

# ---- Pre-commit ----
pre-commit-install:
	uv run pre-commit install

pre-commit-run:
	uv run pre-commit run --all-files

# ---- 数据库 ----
migrate:
	uv run alembic upgrade head

seed:
	uv run python -m src.freqtrade_bridge.seeds.seed_strategies

seed-all:
	uv run python -m src.freqtrade_bridge.seeds.seed_all

# ---- Docker ----
docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f
