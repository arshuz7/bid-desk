-include .env
export

.PHONY: install lint format test test-db schema validate-labels label-template db-up db-down migrate extract eval eval-holdout

install:
	uv sync

lint:
	uv run ruff format --check
	uv run ruff check
	uv run lint-imports

format:
	uv run ruff format
	uv run ruff check --fix

test:
	uv run pytest -m "not db"

test-db:
	uv run pytest -m db

schema:
	uv run python -c "import json; from bidesk.schemas.labels import label_json_schema; print(json.dumps(label_json_schema(), indent=2))" > data/labels/label.schema.json
	uv run python -c "import json; from bidesk.schemas.labels import ask_json_schema; print(json.dumps(ask_json_schema(), indent=2))" > data/labels/ask.schema.json

DIR ?= data/labels/dev
validate-labels:
	uv run python -m bidesk.evals.validate_labels $(DIR)

OUT ?= data/labels/drafts
label-template:
	@test -n "$(TENDER)" || { echo "usage: make label-template TENDER=<tender_id> [OUT=<dir>]" >&2; exit 1; }
	uv run python -m bidesk.evals.label_template $(TENDER) --out $(OUT)

db-up:
	@test -f .env || { echo "Missing .env: copy .env.example to .env and fill it in." >&2; exit 1; }
	docker compose up -d --wait db

db-down:
	docker compose down

migrate:
	uv run python -m bidesk.db migrate

extract:
	@echo "make extract is not implemented until story 2.4" >&2
	@exit 1

eval:
	@echo "make eval is not implemented until story 2.5" >&2
	@exit 1

eval-holdout:
	@echo "make eval-holdout is not implemented until story 5.6" >&2
	@exit 1
