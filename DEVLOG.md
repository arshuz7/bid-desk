# Dev log

An estimate before each task and the actual time after it.

| Date | Story | Task | Estimate | Actual | Notes |
| --- | --- | --- | --- | --- | --- |
| 2026-10-10 | 1.3 | Scaffold: pyproject (uv), ruff, pytest, Makefile, docker-compose, .env.example, CI | 1.5 h (Claude's guess) | 20 minutes | Started 03:35 MDT |
| 2026-10-10 | 1.4 | Harness basics: .claude/settings.json (ruff hook, fast-test Stop hook, holdout deny rules), rules for prompts and governance | 1 h (Claude's guess) | | Started 04:46 MDT |
| 2026-10-10 | 1.5 | Docs: finalized field design (architecture, evals, labelling guide, decisions, roadmap, CLAUDE.md), holdout-ID handling, story 2.0 | Not logged before starting (missed) | | Design from a separate three-analyst review session; diff left uncommitted for review |
| 2026-10-10 | 1.5 | Schema code: fields.py, labels.py, validators, JSON Schema export, label validator CLI, import-linter | 2 h (Claude's guess) | ~5 min of build time | Started 15:06 MDT, done 15:11; PR #38 merged 2026-10-21 |
| 2026-10-21 | 1.6 | tracing.py and llm.py: spans, cost, $2/day cap, Claude structured output, Voyage embeddings | 1.5 h (Claude's guess) | ~6 min of build time | Started 18:17 MDT, done 18:23 |
| 2026-10-22 | 2.0 | Scanned files check (12 files, 3 tenders) | 15 min (roadmap) | 20 min (developer) | All drawings or site photos; 3 tenders become holdout-eligible |
| 2026-10-24 | 2.1 | Choose the 8 holdout tenders (H1–H8), holdout folder, deny rules in settings.local.json, refusal tested | 30 min (roadmap) | 35 min (developer) | Picked at random within each group (wheel of names); IDs kept outside the repo |
| 2026-10-24 | 2.2 prep | Labelling tools: make label-template, Ask question file + validator, tender_contact field | 1 h (Claude's guess) | ~3 min of build time | Started 00:06 MDT, done 00:09 |
| 2026-10-29 | 1.7 | sql/0001_init.sql, db.py (migrate), config.py, append-only triggers, views, db tests in CI | 1.5 h (Claude's guess) | ~17 min (incl. waiting on Docker and the audit fixes) | Started 20:05 MDT, done 20:22; fixes from the bid-desk-54 audit included |
