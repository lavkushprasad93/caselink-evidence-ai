COMPOSE = docker compose -f infra/docker-compose.yml --env-file .env

.PHONY: up down logs test lint migrate

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

test:
	cd apps/api && pytest
	cd apps/web && pnpm test --run

lint:
	cd apps/api && ruff check . && black --check . && mypy .
	cd apps/web && pnpm lint

migrate:
	cd apps/api && alembic upgrade head
