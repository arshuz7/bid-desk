# Evaluation

How extraction and Ask are scored. Results and the changelog of measured changes go in `EVALS.md`
at the repo root. The field types are defined in [architecture.md](architecture.md#field-schema).

## Splits

| Split | Tenders | Where labels live | Who runs it |
| --- | --- | --- | --- |
| Holdout | 8, labelled by hand before any extraction prompt exists | `~/bidesk-holdout/`, outside the repo | Only you, with `make eval-holdout`, at most twice (Week 5 and final) |
| Dev | 12, drafted by the `tender-labeller` subagent and checked value by value against the cited page | `data/labels/dev/` | `make eval`, any time |
| Smoke | 5 synthetic tenders (see decision O2) | `data/smoke/` | CI on every PR |
| Spare | The remaining 5 real tenders | none | Demo rehearsal, ad hoc testing |

**Choosing the holdout.** Stratify it so it isn't easier than dev. A suggested mix of the 8:
- 3 Parks Canada: one tender, one RFP or design-build, one two-stage
- 2 Canada Lands: one qualification, one RFP
- 1 NRCan or RCMP
- 2 municipal

Include at least 4 tenders with addenda. Leave out the 3 tenders with scanned files unless OCR
is built (decision O6). Record the chosen IDs in DEVLOG.md, not in the repo.

## Label format

One JSON file per tender, named `<tender_id>.json`. Labels reuse the value types from
`bidesk.schemas`, and CI validates every dev label against the exported JSON Schema.

```json
{
  "schema_version": 1,
  "tender_id": "synthetic-example",
  "labelled_by": "hand",
  "labelled_on": "2026-10-15",
  "minutes": 35,
  "fields": {
    "project_title": {
      "status": "found",
      "value": "Example Trail Bridge Replacement",
      "evidence": [{"file": "itt-example.pdf", "page": 1}]
    },
    "closing_at": {
      "status": "found",
      "value": "2026-11-20T14:00:00-07:00",
      "evidence": [{"file": "addendum-002-example.pdf", "page": 1}],
      "history": [
        {"value": "2026-11-13T14:00:00-07:00", "evidence": [{"file": "itt-example.pdf", "page": 3}]}
      ]
    },
    "est_value": {"status": "not_stated"},
    "certifications": {
      "status": "found",
      "value": ["COR"],
      "evidence": [{"file": "itt-example.pdf", "page": 7}]
    },
    "eval_criteria": {
      "status": "found",
      "value": [
        {"name": "Price", "weight": "70", "unit": "percent"},
        {"name": "Schedule", "weight": "30", "unit": "percent"}
      ],
      "evidence": [{"file": "itt-example.pdf", "page": 12}]
    }
  }
}
```

- Every one of the 10 fields must be present. The example shows five for brevity.
- `not_stated` means the tender genuinely doesn't say. It's the ground truth for null honesty.
- Labels hold no quotes. Extraction output carries quotes, and the grounding check verifies them
  against the page.
- A label value is the final state after all addenda. `history` is optional and records values
  that addenda replaced (decision O1).
- Labels never contain procurement contacts' names, emails or phone numbers.

## How each field is scored

| Field | Value type | Counted correct when |
| --- | --- | --- |
| Project title | `str` | Normalized match (case, punctuation, whitespace) |
| Issuing organization | `str` | Normalized match, or a match in `evals/aliases.yaml` (for example "Parks Canada Agency" = "Parks Canada") |
| Tender/reference number | `str` | Exact match after stripping spaces |
| Closing date and time | `AwareDatetime` | Same instant once both are in America/Edmonton |
| Site meeting | `SiteMeeting` | Date and mandatory flag both match; a time, if both give one, must also match |
| Project location | `str` | Normalized match, or the LLM judge accepts the paraphrase |
| Estimated value | `Decimal` | Within $1 |
| Mandatory certifications | `list[str]` | Same set after alias normalization; report F1 alongside |
| Bonding/insurance | `list[BondingItem]` | Same set of (kind, amount, unit) |
| Evaluation criteria | `list[Criterion]` | Same criteria (the judge matches wording) and exact weights |

**Status comes first.** Scorers compare status before value:
- Label `not_stated`, prediction `not_stated`: correct, and counts toward null honesty.
- Label `not_stated`, prediction `found`: wrong (an invented answer).
- Label `found`, prediction `not_stated` or `failed`: wrong.
- `failed` is never correct.

Every scorer gets unit tests, especially the date, list and judge-based ones.

## The six metrics

Always reported as counts and percentages (for example 71/80, 89%).

| Metric | How it's measured | Target |
| --- | --- | --- |
| Field accuracy | Fields scored correct, over all 10 fields | ≥ 85% dev; holdout reported as is |
| Null honesty | Truly absent fields returned as `not_stated` | ≥ 90% |
| Citation accuracy | Cited file and page contain the answer (extraction and Ask) | ≥ 95% |
| Review catch rate | Wrong fields that were flagged for review | ≥ 80% |
| Review load | All fields flagged | ≤ 25% |
| Cost and latency | Average USD and seconds per tender, end to end | Under $0.25 and 60 s |

Every run reports the pipeline it used (baseline, workers, or workers plus verifier), so EVALS.md
can compare the three.

## Ask eval

- 3 questions per labelled tender (60 in total), each with a reference answer and its file and
  page.
- At least one question per tender has no answer in the tender. The correct reply is "not stated
  in this tender".
- Scored on: answer correct (LLM judge against the reference), citation correct, and refusal
  correct.

## Rules

- **Never tune on the holdout.** Agents can't read it: `.claude/settings.json` denies its path.
  That doesn't stop you, so log every holdout run with its date in EVALS.md.
- **The holdout is small.** Eight tenders are 80 fields, so one field moves accuracy by 1.25
  points. Don't claim gaps under about 5 points. Give the count behind catch rate.
- **CI gate.** Run the dev eval 3 times on unchanged code and record the spread. CI fails only
  when smoke accuracy drops by more than that spread plus one field.
- **Every prompt or pipeline change gets a changelog row.** It records before and after counts
  and one line on why.
- Results are written to `evals/results/<timestamp>-<split>.json`, with the git SHA, prompt
  versions and cost.
