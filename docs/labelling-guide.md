# Labelling guide

How to label one tender. Use it for every label, holdout and dev alike, so the two splits mean
the same thing. The file format and how labels are scored are in [evals.md](evals.md#label-format).
All examples below are synthetic.

## Before you start

1. Open every in-scope file of the tender: the solicitation, all addenda, appendices and
   Division 01 specifications. Skip drawings and reference files (directories, information-
   session slides, background reports). Retrieval indexes the same roles, so a value you find
   outside them can't be found by extraction either.
2. Read the addenda in order. A label records the **final** state after all of them.
3. Note the start time. `minutes` goes in the header.

## General rules

- **One deciding source.** `evidence` is the single `{file, page}` that settles the value: for a
  value an addendum changed, the addendum page. Don't list every page that repeats it.
- **`accept`** lists alternates that should also count as correct, such as a French title or a
  short form of the reference number. Use it sparingly.
- **`history`** is required whenever an addendum changed the field. List each replaced value,
  oldest first, with the file that stated it.
- **"None" is `not_stated`.** If the tender explicitly says there is none ("no site visit will
  be held"), label `not_stated` and quote the gist in `note`.
- **Q&A counts only through an addendum.** An answer counts only if it was issued as, or
  incorporated by, an addendum.
- **A reissued solicitation replaces the original.** Cite the reissue.
- **Scanned pages still count.** Never label a field `not_stated` because its only source is a
  scanned page. Label what the page says and cite it.
- **No contacts.** Never record procurement contacts' names, emails or phone numbers, in any
  field or note.

## Per field

**Project title.** The English title from the cover. Put the French title in `accept`.
`"value": "Example Creek Trail Bridge Replacement", "accept": ["Remplacement du pont du sentier Example Creek"]`

**Issuing organization.** The owner, not a consultant issuing on its behalf. If an engineering
firm issues the tender for a town, the town is the issuer.
`"value": "Town of Example"`

**Reference number.** The solicitation number on the cover, never the CanadaBuys notice ID.
Put a short form in `accept`.
`"value": "5P000-26-9999", "accept": ["26-9999"]`

**Closing date and time.** The final closing after all addenda, with its time zone. Compute it
when an addendum only describes the change ("extended by one week"), and cite that addendum.
For two-stage and qualification tenders, use the closing of the stage this document solicits.
`"value": "2026-11-20T14:00:00-07:00", "history": [{"value": "2026-11-13T14:00:00-07:00", "file": "itt-example.pdf"}]`

**Site meeting.** With several visits, the earliest. `mandatory` is true if any visit is
mandatory, and null if the tender doesn't say. Use a date alone when no time is given. "By
appointment" with no scheduled date is `not_stated`.
`"value": {"when": "2026-11-05", "mandatory": true}`

**Location.** The town or park plus the site, not a street address.
`"value": "Example Creek day-use area, Example National Park"`

**Estimated value.** A stated figure or band, as `low` and `high` (equal for a single figure).
A "not to exceed" ceiling is `not_stated`, with the ceiling in `note`.
`"value": {"low": "250000", "high": "500000"}`

**Mandatory certifications.** Company-level requirements at bid or award: COR, SECOR,
prequalification, and organization security clearance such as Designated Organization
Screening. Individual workers' tickets and personal clearances don't count.
`"value": ["COR", "Designated Organization Screening"]`

**Bonding and insurance.** One item per requirement. "Bid bond OR bid deposit" is two items. A
tiered formula ("10% of the first $250,000 plus 5% of the excess") is listed with `amount` and
`unit` both null; explain it in `note`.
`"value": [{"kind": "bid_bond", "amount": "10", "unit": "percent"}, {"kind": "performance_bond", "amount": null, "unit": null}]`

**Evaluation criteria.** A lowest-price award is `basis: "lowest_compliant_price"` with no
criteria. Otherwise list top-level criteria only, with their weights; ignore sub-criteria and
pass marks. Pass/fail criteria have `unit: "pass_fail"` and a null weight.
`"value": {"basis": "weighted", "criteria": [{"name": "Price", "weight": "60", "unit": "percent"}, {"name": "Technical", "weight": "40", "unit": "percent"}]}`

## Before you save

- [ ] All 10 fields are present, each `found` with one evidence item or `not_stated`.
- [ ] Every value changed by an addendum has `history`.
- [ ] No contact names, emails or phone numbers anywhere.
- [ ] `minutes`, `addenda_count` and `kind` are filled in.
- [ ] The label validator passes on the file.
