.PHONY: help setup setup-all up-infra up-app up-batch up-obs up down logs migrate ingest-blog migrate-v1 eval test lint fmt

COMPOSE := docker compose
INFRA    := -f deploy/compose.infra.yml
APP      := -f deploy/compose.app.yml
BATCH    := -f deploy/compose.batch.yml
OBS      := -f deploy/compose.observability.yml
DEV      := -f deploy/compose.dev.yml

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "Setup"
	@echo "  setup           install uv + sync dev deps"
	@echo "  setup-all       full stack: infra up + migrate + indexes"
	@echo ""
	@echo "Docker"
	@echo "  up-infra        postgres + qdrant + redis"
	@echo "  up-app          app container"
	@echo "  up-batch        batch container"
	@echo "  up-obs          prometheus + grafana"
	@echo "  up              full stack (infra + app + batch + obs)"
	@echo "  down            stop all"
	@echo "  logs            tail all logs"
	@echo ""
	@echo "DB / Ingest"
	@echo "  migrate         run SQL migrations (psql)"
	@echo "  ingest-blog     run blog ingest job"
	@echo "  migrate-v1      migrate v1 export JSONL to Postgres"
	@echo ""
	@echo "Dev"
	@echo "  test            run pytest (unit)"
	@echo "  eval            run evaluation suite (app must be running)"
	@echo "  lint            ruff check"
	@echo "  fmt             ruff format"

setup:
	@which uv > /dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
	uv sync --group dev

setup-all: up-infra
	@sleep 3
	$(MAKE) migrate
	@echo "Infra ready. Run 'make up-app' to start the app."

up-infra:
	$(COMPOSE) $(INFRA) up -d

up-app:
	$(COMPOSE) $(APP) up -d

up-batch:
	$(COMPOSE) $(BATCH) up -d

up-obs:
	$(COMPOSE) $(OBS) up -d

up:
	$(COMPOSE) $(INFRA) $(APP) $(BATCH) $(OBS) up -d

down:
	$(COMPOSE) $(INFRA) $(APP) $(BATCH) $(OBS) down

logs:
	$(COMPOSE) $(INFRA) $(APP) $(BATCH) logs -f

dev:
	$(COMPOSE) $(INFRA) $(DEV) up -d

migrate:
	bash infra/scripts/init_db.sh

ingest-blog:
	uv run python -m batch.main ingest-blog

migrate-v1:
	uv run python -m batch.main migrate-v1

eval:
	uv run python tests/eval/run_eval.py --url http://localhost:8000

test:
	uv run pytest tests/unit/

lint:
	uv run ruff check .

fmt:
	uv run ruff format .
