# tc-agent — AI test pipeline (Model B)

tc-agent writes JUnit 5 tests for one Java class (or method) in a Maven project.
It trusts only the committed code, the tests and git — no memory between runs.

## Agents

| agent | job |
|---|---|
| `tc-orchestrator` | the one you call. Runs the scripts and calls the other agents. |
| `tc-planner` | decides WHAT to test (scenarios, data, evidence). |
| `tc-generator` | writes the test code. Never runs anything. |
| `tc-reviewer` | runs tests, coverage and mutations; decides ACCEPT or repair. |

## Setup (once per repo)

1. Maven project with JUnit 5. JaCoCo and PIT (with `pitest-junit5-plugin`) in the pom, or they are called from the CLI.
2. Git, and Python 3 with `pip install -r .github/agents/tc-agent/tc-requirements.txt`.
3. Copilot custom agents enabled; `.test-agent/` in `.gitignore` (run files live there).

## How to run

In Copilot Chat choose **tc-orchestrator** and say what you want, for example:

    Generate tests for SimpleCalculatorService, mode legacy, commit
    Generate tests for OrderService.create, mode spec-driven, spec docs/order-spec.md, interactive

The orchestrator turns this into `tc_orchestrate.py start` with these options:

| option | meaning |
|---|---|
| target | `ClassName` or `ClassName.methodName`. One or a list. |
| `--mode legacy` (default) | Freeze the CURRENT behaviour, bugs included. Tests describe what the code does now. |
| `--mode spec-driven` | Tests follow a specification. A failing test may mean the code is wrong → NEEDS_TRIAGE, not a fix. |
| `--spec <path>` | The specification file for spec-driven mode. |
| `--interactive` | The planner may ask you questions. Also turns off the freshness guard. |
| `--impl-cap <n>` (3) | Max repair rounds of the test code per plan. |
| `--plan-cap <n>` (2) | Max new plan versions. |
| `--commit` | Commit the new test files at the end — see **Commit**. |

## Flow

1. **start** — derive-state checks the target: git state, tests, JaCoCo, PIT. Verdict:
   - `DONE` — tests exist, green, gates met, code unchanged → nothing to do;
   - `PLAN` — something is missing (no tests, coverage/mutation gap, untested or changed methods, stale tests);
   - `RED` — existing tests fail → a human must look;
   - `BLOCKED` — target has uncommitted changes, is not committed, or is too fresh (legacy only).
2. **PLAN → GENERATE → REVIEW**, repeated until the reviewer accepts or a cap is hit.
   The reviewer's decision picks the next step: repair the code, repair the plan, or accept.
3. **RESEAL** — tests that are still green after a code change get the new commit sha.
4. **FINISH** — writes `run-report.md`, prints it, and commits if `--commit` was given.

Outcomes: `DONE`, `DONE_PARTIAL` (some scenarios are placeholders), `BLOCKED`, `RED`, `ESCALATED` (a cap was hit or a human decision is needed).
Commit your production code first — a dirty target is always BLOCKED.

## Configuration

- **`.github/agents/tc-agent/tc-project-profile.md`** (json block):
  - `branch_coverage_target_scope` (0.80), `mutation_score_target_scope` (0.70) — the gates;
  - `freshness_days` (7) — legacy refuses code committed less than N days ago (use `--interactive` to override);
  - `instruction_paths` — extra style files for the agents;
  - `tooling` — only if the pom has no JaCoCo/PIT versions.
- **Style rules** — the agents read `.github/copilot-instructions.md`,
  `.github/instructions/*.instructions.md` (by `applyTo`) and `AGENTS.md`.
  Repo rules override the default style in `tc-test-conventions.md` §B, never the rules in §A.
- **`AGENTS.md`** — `tc-agent-protected-branches: master, main, release/*` (default: `master`).

Default style: names `shouldXxxWhenYyy`, `// given / // when / // then`, AssertJ,
Mockito for repositories, class under test as a field, class `<Target>Test`.

## Commit (`--commit`)

- Only on `DONE` or `DONE_PARTIAL`, and only the test files this run wrote.
- On a protected branch it first creates a new branch `tc-agent/<target>/<run-id>`.
- Message = short title + 2–5 sentence summary from the reviewer + numbers (gates, counts).
- Never pushes.

## What you get

Every run has its own folder `.test-agent/runs/<target>/<run-id>/`:
`run.json`, `derive-state.md`, `context-pack.md`, `plan-vN.md`,
`generation-report-vN[-rM].md`, `review-vN-rM.md`, `checks/`, `run-report.md`.
Old runs are never read again and never deleted.

Each generated test method has a Javadoc with plain-text metadata:

    tc-agent: generated
    tc-agent-mode: legacy
    tc-agent-characterizes: SimpleCalculatorService@29aeef6a

A scenario that cannot be tested (e.g. code reads `LocalDateTime.now()`) becomes an
empty `@Disabled("AI deferred: …")` method with `tc-agent-deferred: <reason>`.
Do not delete placeholders — they tell the next run the gap is known.

## Good to know

- Only the scripts run Maven; the agents never do. To start again, just run again.
- In PowerShell, quote `-D` args: `mvn "-Dtest=FooTest"`.
- Dev tests: `tools/tc_test_*.py`; real Maven smoke test: `python .github/agents/tc-agent/tools/tc_smoke_pipeline.py`.
