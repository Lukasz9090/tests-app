# Mode: spec-driven

The oracle is the specification named in `run.json` (`spec`); its text is the
SPEC section of the context pack. A test asserts what the spec says, so a failing
test may mean the CODE is wrong. The scope is the spec only: branches the spec
does not describe are left to a characterization run.

## Planner

- Read the spec before you plan. Every scenario cites the requirement it comes
  from (`human_decision` / `api_schema` evidence pointing at the spec lines) and
  names it in `requirement` (the id, or the heading when the spec has no ids). The target's lines show
  how to call the code; they are not a substitute for the spec.
- `SPEC_REVIEW` in `derive-state.md` means the gates are met: compare the spec
  with the tests (their `spec` entries in derive-state) and plan only the
  requirements no test covers — `COMPLETE` with `reason` when every one is.
  `COVERAGE_GAP`, `MUTATION_GAP` and `STALE` are context here, not work: say in
  `context.notes` that a characterization run closes them.
- A test disabled as `AI spec-mismatch` is a known defect of the code: plan it
  again (`replaces`, to re-enable) only when the target changed since.
- A requirement that is ambiguous, or that the spec contradicts elsewhere: in an
  interactive run ask (`modes/interactive.md`); otherwise status
  `NEEDS_CLARIFICATION` with a `reason` quoting both. Never pick a side.
- No `context.target_sha`.

## Generator

- First Javadoc line: `AI-generated test. Based on the specification <spec file>.`
- Metadata (`conventions.md` §A1): `tc-agent-mode: spec-driven, interactive: <run.json>`
  and `tc-agent-spec: <spec file>#<requirement>` from the scenario's
  `requirement`; never `tc-agent-characterizes`.
- Feedback with `scope: "disable"`: the code does not do what the spec says. Keep
  the method and its body, add `@Disabled("AI spec-mismatch: <short>")` and
  `tc-agent-note: spec mismatch: <spec says X, code does Y>`; change nothing else.
  Report it `IMPLEMENTED` with that note.

## Reviewer

- Stage 1: every method of this run carries `tc-agent-spec`, none carries
  `tc-agent-characterizes`. A method disabled with `AI spec-mismatch:` after your
  own `disable` feedback is conformant.
- A failing assertion in a test THIS run wrote, with a setup that is correct and an
  expectation that matches the spec text: a `spec_mismatch` finding (quote the
  spec, the expected and the actual value) and **REPAIR_IMPLEMENTATION** with
  feedback `scope: "disable"` for that method. Never change the test to agree
  with the code — that certifies the bug. When the expectation does not match the
  spec, it is an ordinary implementation (or plan) defect.
- A failing test this run did NOT write is **NEEDS_TRIAGE**.
- When every remaining failure is disabled as a mismatch: **ACCEPT_PARTIAL**;
  `finish` lists the mismatches at the top of the report.
