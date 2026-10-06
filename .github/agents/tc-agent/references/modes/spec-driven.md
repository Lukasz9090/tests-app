# Mode: spec-driven

The oracle is the specification named in `run.json` (`spec`). A test asserts what
the spec says, so a failing test may mean the CODE is wrong.

## Planner

- Read the spec before you plan. Every scenario cites the spec passage it comes
  from; the target's lines show how to call the code, they are not a substitute
  for the spec.
- When the spec and the code disagree, do NOT pick a side: status
  `NEEDS_CLARIFICATION` with a `conflict` block that quotes both.
- No `characterization`, no `context.target_sha` requirement.

## Generator

- First Javadoc line: `AI-generated test. Based on a specification provided at generation time (not stored in the repo).`
- Metadata (`conventions.md` §A1): `tc-agent-mode: spec-driven, interactive: <run.json>`;
  never `tc-agent-characterizes`.

## Reviewer

- Stage 1: no method of this run carries `tc-agent-characterizes`.
- A failing assertion is **NEEDS_TRIAGE**: the code may be wrong rather than the
  test. Record the spec reference, the expectation and the actual value in
  `triage`. Never change the test to agree with the code — that certifies the bug.
