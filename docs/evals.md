# Evaluation

How extraction and Ask are scored. Results and the changelog of measured changes go in `EVALS.md`
at the repo root. The field types are defined in [architecture.md](architecture.md#field-schema).

## Splits

| Split | Tenders | Where labels live | Who runs it |
| --- | --- | --- | --- |
| Holdout | 8 eligible tenders (rules below), labelled by hand before any extraction prompt exists | `~/bidesk-holdout/`, outside the repo | Only you, with `make eval-holdout`, at most twice (Week 5 and final) |
| Dev | 12, drafted by the `tender-labeller` subagent and checked value by value against the cited page | `data/labels/dev/` | `make eval`, any time |
| Smoke | 5 synthetic tenders (see decision O2) | `data/smoke/` | CI on every PR |
| Spare | The remaining 5 real tenders, including every tender excluded from the holdout | none | Demo rehearsal, ad hoc testing |

**Holdout eligibility.** These exclusions are written down so the holdout isn't silently made
easier than dev:
- Exclude the 3 tenders with scanned files (26-0139, 26-0163, 26-0219), unless the story 2.0
  check shows their scanned files are only drawings.
- Exclude the 1,208-page Wood Buffalo tender (`muni-rmwb-fort-mckay-centre`).
- Excluded tenders go to Spare. With all 4 excluded, Spare is those 4 plus 1 more, and Dev is
  12 of the remaining 13.
- Include at least 4 tenders where an addendum actually changes a labelled field. This can't
  be known for certain before labelling, so in story 2.1 skim each candidate's addenda and pick
  ones that visibly change a closing time, site meeting, bonding or criteria. If labelling
  shows fewer than 4, record that in DEVLOG.md rather than swapping tenders after the fact.

**Choosing the holdout.** Stratify it so it isn't easier than dev. A suggested mix of the 8:
- 3 Parks Canada: one tender, one RFP or design-build, one two-stage
- 2 Canada Lands: one qualification, one RFP
- 1 NRCan or RCMP
- 2 municipal

**Keep the chosen IDs out of the repo.** They live only in the holdout directory, as the label
file names. DEVLOG.md refers to holdout tenders as H1–H8, never by ID. Their PDFs still sit in
`data/raw/`, so after choosing, add deny rules for them to the gitignored
`.claude/settings.local.json`:
- `Read` and `Edit` on `data/raw/<tender_id>/**`
- `Bash(*<tender_id>*)`
- `Read` and `Edit` on `.claude/settings.local.json` itself, so an agent can't read the list

Confirm in a fresh session that reading one of those files is refused. This stops agents from
reading holdout PDFs while tuning. It doesn't cover database rows once a holdout tender is
ingested, so ingest the holdout tenders only when you run `make eval-holdout`.

## Label format

One JSON file per tender, named `<tender_id>.json`. Labels reuse the value types from
`bidesk.schemas`, and CI validates every dev label against the exported JSON Schema. How to
decide each value is in [labelling-guide.md](labelling-guide.md).

**Header:** `schema_version`, `tender_id`, `kind` (as in the manifest), `addenda_count`,
`labelled_by`, `labelled_on`, `minutes`.

**Each field:**
- `status`: `found` or `not_stated`. Labels can never be `failed`.
- `value`: the final value after all addenda; omitted when `not_stated`.
- `evidence`: exactly one deciding source, as `[{"file": ..., "page": ...}]`, with no quote.
- `accept` (optional): acceptable alternates, such as a French title or a short reference number.
- `note` (optional): why a value was chosen, or what the tender said when a field is `not_stated`.
- `history` (`[{"value": ..., "file": ...}]`): required whenever an addendum changed the field.
  It lists the replaced values, oldest first, with the file that stated each one.

All 10 fields are present in every label. A complete example, with synthetic values only:

```json
{
  "schema_version": 1,
  "tender_id": "synthetic-example",
  "kind": "tender",
  "addenda_count": 2,
  "labelled_by": "hand",
  "labelled_on": "2026-10-15",
  "minutes": 40,
  "fields": {
    "project_title": {
      "status": "found",
      "value": "Example Creek Trail Bridge Replacement",
      "evidence": [{"file": "itt-example.pdf", "page": 1}],
      "accept": ["Remplacement du pont du sentier Example Creek"]
    },
    "issuing_org": {
      "status": "found",
      "value": "Parks Canada",
      "evidence": [{"file": "itt-example.pdf", "page": 1}]
    },
    "reference_no": {
      "status": "found",
      "value": "5P000-26-9999",
      "evidence": [{"file": "itt-example.pdf", "page": 1}],
      "accept": ["26-9999"]
    },
    "closing_at": {
      "status": "found",
      "value": "2026-11-20T14:00:00-07:00",
      "evidence": [{"file": "addendum-002-example.pdf", "page": 1}],
      "history": [{"value": "2026-11-13T14:00:00-07:00", "file": "itt-example.pdf"}]
    },
    "site_meeting": {
      "status": "found",
      "value": {"when": "2026-11-05", "mandatory": true},
      "evidence": [{"file": "itt-example.pdf", "page": 2}]
    },
    "location": {
      "status": "found",
      "value": "Example Creek day-use area, Example National Park",
      "evidence": [{"file": "itt-example.pdf", "page": 1}]
    },
    "est_value": {
      "status": "found",
      "value": {"low": "250000", "high": "500000"},
      "evidence": [{"file": "itt-example.pdf", "page": 4}]
    },
    "certifications": {
      "status": "not_stated",
      "note": "Section 4 says no safety prequalification is required."
    },
    "bonding_insurance": {
      "status": "found",
      "value": [
        {"kind": "bid_bond", "amount": "10", "unit": "percent"},
        {"kind": "bid_deposit", "amount": "10", "unit": "percent"},
        {"kind": "performance_bond", "amount": null, "unit": null},
        {"kind": "cgl_insurance", "amount": "5000000", "unit": "CAD"}
      ],
      "evidence": [{"file": "itt-example.pdf", "page": 9}],
      "note": "Bid security is a bond OR a deposit. The performance bond is tiered: 10% of the first $250,000 plus 5% of the excess."
    },
    "eval_criteria": {
      "status": "found",
      "value": {"basis": "lowest_compliant_price", "criteria": []},
      "evidence": [{"file": "itt-example.pdf", "page": 12}]
    }
  }
}
```

- `not_stated` means the tender genuinely doesn't say, or explicitly says "none". It's the
  ground truth for null honesty.
- Labels hold no quotes. Extraction output carries quotes, and the grounding check verifies them
  against the page.
- The label's evidence is one deciding source. Citation accuracy doesn't require the prediction
  to cite the same page (see [Grounding and citation](#grounding-and-citation)).
- Labels never contain procurement contacts' names, emails or phone numbers.

## How each field is scored

**Status comes first.** Scorers compare status before value:
- Label `not_stated`, prediction `not_stated`: correct, and counts toward null honesty.
- Label `not_stated`, prediction `found`: wrong (an invented answer).
- Label `found`, prediction `not_stated` or `failed`: wrong.
- `failed` is never correct.

When both are `found`, the value decides:

| Field | Value type | Counted correct when |
| --- | --- | --- |
| Project title | `str` | Normalized match (case, punctuation, whitespace), or any `accept` value |
| Issuing organization | `str` | Normalized match, any `accept` value, or a match in `evals/aliases.yaml` (for example "Parks Canada Agency" = "Parks Canada") |
| Tender/reference number | `str` | Exact match after stripping spaces, or any `accept` value |
| Closing date and time | `AwareDatetime` | Same instant once both are in America/Edmonton |
| Site meeting | `SiteMeeting` | Date and mandatory flag both match |
| Project location | `str` | Normalized match or any `accept` value; otherwise the LLM judge decides whether the paraphrase is the same place |
| Estimated value | `Money` | Both `low` and `high` within $1 |
| Mandatory certifications | `list[str]` | Same set after alias normalization |
| Bonding/insurance | `list[BondingItem]` | Same set of (kind, amount, unit) |
| Evaluation criteria | `EvalCriteria` | Same `basis`, and the same set of criteria (the judge matches wording) with exact weights |

For certifications, bonding and evaluation criteria, also report item-level F1 as a secondary
column next to the exact set match. It doesn't change whether the field counts as correct.

Every scorer gets unit tests, especially the date, list and judge-based ones.

## Grounding and citation

- **Grounding:** the quote appears on the cited file and page (fuzzy match, after normalizing
  hyphenation and line breaks). Where a date or amount appears literally in the quote, it is
  also parsed and must match the value. Derived values, such as a closing date computed from
  "extended by one week", skip that second check, because they never appear verbatim.
- **Citation accuracy (extraction):** a field counts when its quote passes grounding on the
  cited file and page **and** its value is scored correct. The cited page doesn't have to match
  the label's evidence page; a tender often states the same fact in several places.
- **Citation accuracy (Ask):** the cited file and page match the reference answer's.

## The six metrics

Always reported as counts and percentages (for example 71/80, 89%).

| Metric | How it's measured | Target |
| --- | --- | --- |
| Field accuracy | Fields scored correct, over all 10 fields | ≥ 85% dev; holdout reported as is |
| Null honesty | Truly absent fields returned as `not_stated` | ≥ 90% |
| Citation accuracy | As defined in [Grounding and citation](#grounding-and-citation), for extraction and Ask | ≥ 95% |
| Review catch rate | Wrong fields that were flagged for review | ≥ 80% |
| Review load | All fields flagged | ≤ 25% |
| Cost and latency | Average USD and seconds per tender, end to end | Under $0.25 and 60 s |

Every run reports the pipeline it used (baseline, workers, or workers plus verifier), so EVALS.md
can compare the three.

**Reporting slices.** Every metric is also reported for two slices: addendum-changed fields
(the label's `history` is non-empty) versus the rest, and each tender kind (tender, RFP,
two-stage, qualification, design-build). Slices on the holdout are small, so give counts.

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
