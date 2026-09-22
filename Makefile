.PHONY: help install setup lint lint-fix test infra infra-down migrate api worker reindex eval

help:
	@echo "make install    — поставить зависимости из uv.lock"
	@echo "make setup      — install + миграции"
	@echo "make infra      — поднять базу с pgvector и движок процессов"
	@echo "make infra-down — остановить инфраструктуру вместе с томами"
	@echo "make migrate    — применить db/migrations/*.sql"
	@echo "make api        — приложение на :8000"
	@echo "make worker     — воркер устойчивых процессов"
	@echo "make reindex    — досчитать векторы фрагментам без них"
	@echo "make eval       — прогон метрик (весь набор: make eval FULL=1)"
	@echo "make lint       — ruff"
	@echo "make lint-fix   — ruff с правкой"
	@echo "make test       — pytest"

install:
	uv sync --frozen

setup: install migrate

lint:
	uv run ruff check .

lint-fix:
	uv run ruff check --fix .

test:
	uv run pytest -q

infra:
	docker compose up -d

infra-down:
	docker compose down -v

migrate:
	uv run python -m app.core.migrate

api:
	uv run uvicorn app.main:app --reload --port 8000

worker:
	uv run python -m app.temporal_worker

reindex:
	uv run python -m app.rag.reindex

eval:
	uv run python -m evals.runner $(if $(FULL),--full,)
