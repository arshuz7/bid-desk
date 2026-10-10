.PHONY: install lint format test db-up db-down migrate extract eval eval-holdout

install:
	uv sync

lint:
	uv run ruff format --check
	uv run ruff check

format:
	uv run ruff format
	uv run ruff check --fix

test:
	uv run pytest -m "not db"

db-up: .env
	docker compose up -d --wait db

db-down:
	docker compose down

.env:
	@echo "Missing .env: copy .env.example to .env and fill it in." >&2
	@exit 1

migrate:
	@echo "make migrate is not implemented until story 1.7" >&2
	@exit 1

extract:
	@echo "make extract is not implemented until story 2.4" >&2
	@exit 1

eval:
	@echo "make eval is not implemented until story 2.5" >&2
	@exit 1

eval-holdout:
	@echo "make eval-holdout is not implemented until story 5.6" >&2
	@exit 1
