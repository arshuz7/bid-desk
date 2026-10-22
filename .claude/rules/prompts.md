---
paths:
  - "src/bidesk/prompts/**"
---

# Prompt files

- A prompt is `src/bidesk/prompts/<prompt_id>/v<N>.md`. A version is released once it is on
  `main`, and a released version is never edited.
- To change a prompt, copy it to `v<N+1>` and edit the copy, using the `new-prompt-version` skill
  (story 3.5; until it exists, copy the file by hand). Point the code at the new version.
- Every prompt change needs a `make eval` run and an `EVALS.md` changelog row with before and
  after counts and one line on why.
- Field names, descriptions and value types come from `FIELD_SPECS` in `schemas/fields.py`.
  Don't hard-code field lists in a prompt.
- The model returns status, value and evidence (`file`, `page`, verbatim `quote`) only. It never
  sets `confidence` or `signals`.
- A prompt never asks the model to submit, sign or price a bid, or to make a go/no-go call.
- The only contact a prompt asks for is `tender_contact`: who the tender says to send questions
  to. Nothing else about people. The Ask prompt may quote that contact, with a citation.
- Never put holdout tenders, holdout labels or their contents in a prompt or few-shot example.
