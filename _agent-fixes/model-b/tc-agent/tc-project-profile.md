# Project Profile

Per-repository configuration for the test pipeline. The Reviewer's check scripts
read the single ```json fence below; nothing else in this file is parsed.

This file lives in the repository on purpose. It used to be looked for under
`.test-agent/`, which is gitignored, so every run silently fell back to the
built-in defaults and no one could see or review the gates.

**Quality gates** are the thresholds `tc_coverage.py` and `tc_mutation.py` must reach
for the target scope — the class, or the single method when the plan names one.
Raise them deliberately; the Reviewer may never lower one to reach ACCEPT.

**Freshness** (`freshness_days`): legacy mode without `--interactive` refuses to
freeze a target whose last commit is younger than this many days — nobody has
validated that behaviour yet, so a green characterization test would certify a
possible bug. derive-state reports such a run as BLOCKED. Default 7.

**Repo instructions** (`instruction_paths`, optional): extra instruction files the
context pack puts into REPO CONVENTIONS, relative to the repo root and allowed
outside `.github` (e.g. `docs/code-conventions.instruction.md`). Files under
`.github/copilot-instructions.md`, `.github/instructions/*.instructions.md` and
`AGENTS.md` are picked up without being listed. Repo instructions tune style
only; they never override `tc-test-conventions.md` §A.

**Tooling** is deliberately absent. `tool_version()` resolves a version as
CLI flag → this file → the version declared in the pom → the agent default, so a
value here OVERRIDES the pom. This repo's pom pins jacoco 0.8.15 and pitest
1.25.9, and prepare-agent must run the same JaCoCo version as the report goal —
pinning a different one here would make the report reject the exec file. Add a
`tooling` block only when the pom declares no version, or when the pom's version
cannot read the class files of the JDK in use.

```json
{
  "schema_version": 1,
  "quality_gates": {
    "branch_coverage_target_scope": 0.80,
    "mutation_score_target_scope": 0.70
  },
  "freshness_days": 7
}
```
