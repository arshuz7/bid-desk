-include .env
export

.PHONY: install lint format test test-db schema check-manifest validate-labels label-template db-up db-down migrate ingest ingest-dev search extract eval eval-holdout

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

check-manifest:
	uv run python -m bidesk.manifest

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

# Dev corpus only: refuses any tender not in the gitignored data/non-holdout.txt.
ingest:
	@test -n "$(TENDER)" || { echo "usage: make ingest TENDER=<tender_id>" >&2; exit 1; }
	uv run python -m bidesk.cli ingest $(TENDER)

ingest-dev:
	@test -s data/non-holdout.txt || { echo "data/non-holdout.txt is missing or empty" >&2; exit 1; }
	uv run python -m bidesk.cli ingest $$(grep -v '^#' data/non-holdout.txt)

search:
	@test -n "$(TENDER)" -a -n "$(Q)" || { echo 'usage: make search TENDER=<tender_id> Q="question"' >&2; exit 1; }
	uv run python -m bidesk.cli search $(TENDER) "$(Q)"

extract:
	@echo "make extract is not implemented until story 2.4" >&2
	@exit 1

eval:
	@echo "make eval is not implemented until story 2.5" >&2
	@exit 1

eval-holdout:
	@echo "make eval-holdout is not implemented until story 5.6" >&2
	@exit 1
