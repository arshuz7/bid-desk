---
name: run-eval-and-log
description: Run the dev extraction eval and log it in EVALS.md with before and after counts. Use after any prompt or pipeline change, or when asked to run, compare or report evals.
---

# Run the eval and log it

CLAUDE.md requires an EVALS.md row with before and after counts for every prompt or pipeline
change. This is how.

1. Make sure every dev tender has a finished extract run from the *same* code and prompt
   version: `make extract TENDER=<id>` for each tender in `data/labels/dev/`. The runner refuses
   to mix versions, and you shouldn't reach for `--allow-mixed` to get a number.
2. Run `make eval` (or `make eval PIPELINE=workers`). It prints per-field counts and the metrics,
   writes `evals/results/<timestamp>-dev.json` and appends a row to `EVALS.md`.
3. Fill in the row's **Why** cell: one line on what changed, plus before and after counts from
   the previous row at the **same scorer version** (for example "dates fix: closing_at 9/12 ->
   11/12; accuracy 98/120 -> 100/120").
4. Read the results JSON for the fields that got worse, not just the totals.
5. Report counts with percentages, never percentages alone. "Needs judge" counts are fields only
   the LLM judge (4.1) can settle; they count as wrong until then.

Never:
- run `make eval-holdout`, or read, list or reference the holdout. Only the developer does that.
- claim a gap under about 5 points on the holdout.
- edit an old EVALS.md row, except to fill in its own Why cell.
