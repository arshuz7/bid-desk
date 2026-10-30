---
paths:
  - "src/bidesk/governance/**"
  - "src/bidesk/tracing.py"
  - "src/bidesk/llm.py"
  - "src/bidesk/db.py"
  - "sql/**"
---

# Governance, tracing and the model client

- Never remove, skip or bypass span logging or the $2/day spend cap, including in tests, retries
  and error paths. A call over the cap raises before it reaches the API.
- `spans` and `review_decisions` are append-only: no `UPDATE` or `DELETE`, in code or in
  migrations. A run changes exactly once, from `running` to `succeeded` or `failed` (setting
  `finished_at` and `cost_usd`). Triggers in `sql/0001_init.sql` enforce both; never drop them.
  Current state comes from views (`approved_fields`, `review_queue`).
- `llm.py` is the only module that imports `anthropic` or `voyageai`. It reports spans through
  `tracing` and never imports `governance`; the composition root registers the sink.
- `confidence` and `signals` are set here, never by the model.
- Deterministic checks (grounding against the stored page text) run before LLM checks. Then one
  bounded retry, then the human review queue. Nothing loops on model output.
- Migrations are new numbered files in `sql/`. Never edit one that is on `main`.
- Spans and logs never contain secrets. Prompt text in a span may include a tender's own
  contact details, because it's the tender's public text; never log contacts gathered across
  tenders.
