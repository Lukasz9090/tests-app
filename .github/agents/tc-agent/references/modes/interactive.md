# Interactive run

A human can answer. Ask through your question tool; ALWAYS also record every
question in `context.notes` as `CONFIRM: <ref> — <question>`, so a host that
cannot ask live still leaves them for review (`finish` puts them in the report).

Two rounds, in this order, with separate budgets — the second never eats the first.

## Round 1 — test data (always first)

Take every kind of value off the list that `conventions.md` §A4 sources 1–4
already answer. If nothing is left, write why in `context.notes` ("test data:
covered by docs/test-data-examples.md", "test data: every value comes from existing
tests"). Otherwise ask ONE question listing the uncovered kinds:

    "I need example values for: customer id, account number, transfer type.
     Do you have a file with such examples, or shall we go through a few
     questions? (no = I use neutral placeholders)"

If you were about to write `"1"`, `"KEY-1"`, `"test"` or an invented literal for
an id, account or product code, dictionary key, name or document number, that
kind is uncovered.

- **A path:** read that file (it counts against the 5-file escape hatch), use it,
  and note "test data file: <path> (add it to the project's test-data-examples.md)".
- **Questions:** per KIND, never per field, at most 3 ("Customer ids in this
  system: what does a real one look like?" covers `ownerCustomerId` and
  `coownerCustomerId`). Record each as `{concept, rule, examples, applies_to,
  used_by}` in `context.test_data`, cite it as `human_decision`, and add a note
  "test data worth keeping: <what you were told> (put it in the project's test-data-examples.md)".
- **No:** neutral values (§A4), defer every kind whose meaning decides a branch,
  note "test data declined by the human", and do not ask again in this run.

The plan MUST show what happened: `context.test_data` entries, or a note saying
why no question was needed or that the human declined.

## Round 2 — evidence and what you freeze

- **Short evidence:** ONE precise closed question; record the answer as `human_decision`.
- **Spec-driven:** an ambiguous or self-contradicting requirement gets ONE closed
  question quoting the passage; the answer is `human_decision` evidence.
- **Characterization:** pick the FEW most consequential or non-obvious behaviors
  (an odd branch, a magic value, a suspect guard) and ask "the code does X here —
  freeze it as current behavior, or is X a defect to flag?" At most 3–5
  questions, never one per scenario.
- **Characterization, fresh code:** when `git.age_days` is below the profile's
  `freshness_days`, first ask "the target was last committed N days ago — freeze
  its current behavior as-is?" A "no" is status `BLOCKED` with that reason.
- Record each answer on its scenario in `notes` → a `Note:` line:
  `human-confirmed: <what>` or `reported as defect: <what>`. "I don't know / skip"
  moves the scenario to `deferred` with the question as its `reason`.
