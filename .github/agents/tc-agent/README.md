# tc-agent — AI test pipeline

tc-agent writes JUnit tests for one Java class (or method) in a Maven project.
It trusts only the committed code, the tests and git — no memory between runs.

![tc-agent architecture](docs/architecture.svg)

## Agents

| agent | job |
|---|---|
| `tc-orchestrator` | the one you call. Runs the scripts and calls the other agents. |
| `tc-planner` | decides WHAT to test (scenarios, data, evidence). |
| `tc-generator` | writes the test code. Never runs anything. |
| `tc-reviewer` | runs tests, coverage and mutations; decides ACCEPT or repair. |

## Setup (once per repo)

1. Maven project with JUnit 5 or JUnit 4 — taken from what the module's tests import, from the poms only if it has none (`junit` in the profile overrides both).
2. **JaCoCo and PIT need no pom entry.** The checks call their goals by full coordinates, so an untouched pom works; a version declared in the pom is used, otherwise the agent's default. One exception: on **JUnit 5**, PIT needs `pitest-junit5-plugin` as a plugin dependency in the pom — that cannot be added from the CLI, and without it mutation testing is reported as unavailable.
3. Git, and Python 3 with `pip install -r .github/agents/tc-agent/requirements.txt`.
4. Copilot custom agents enabled; `.test-agent/` in `.gitignore` (run files live there).

## How to run

In Copilot Chat choose **tc-orchestrator** and say what you want, for example:

    Generate tests for SimpleCalculatorService, mode characterization, commit
    Generate tests for OrderService.create, mode spec-driven, spec docs/order-spec.md, interactive
    Generate tests for TransferService, data examples in docs/test-data-examples.md

The orchestrator turns this into `tc_orchestrate.py start` with these options:

| option | meaning |
|---|---|
| target | `ClassName` or `ClassName.methodName`. One or a list. |
| `--mode characterization` (default) | Freeze the CURRENT behavior, bugs included. Tests describe what the code does now. |
| `--mode spec-driven` | Tests follow the specification (`--spec`), only its requirements. Runs even when the gates are met (`SPEC_REVIEW`). A test that fails because the code does not do what the spec says is kept disabled (`AI spec-mismatch`) and listed at the top of the report. |
| `--spec <path>` | The specification file for spec-driven mode. |
| `--interactive` | The planner may ask questions (what to freeze, example data). Also turns off the freshness guard. |
| `--test-data <path>` | A file of example business values, used in any mode (repeatable). Say it in the prompt: "examples are in docs/test-data-examples.md". Without it, only `--interactive` makes the planner ask. |
| `--max-rounds <n>` (3) | Max generate + review rounds in the whole run; a new plan version uses up a round too. Default from the profile's `max_rounds`. |
| `--commit` | Commit the new test files at the end — see **Commit**. |

## Flow

1. **start** — derive-state checks the target: git state, tests, JaCoCo, PIT. Verdict:
   - `DONE` — tests exist, green, gates met, code unchanged → nothing to do;
   - `PLAN` — something is missing (no tests, coverage/mutation gap, untested or changed methods, stale tests
     that fail — a test is stale when the target changed in git after the test's own last commit);
   - `RED` — existing tests fail → a human must look;
   - `BLOCKED` — target has uncommitted changes, is not committed, or is too fresh (characterization only).
2. **PLAN → GENERATE → REVIEW**, repeated until the reviewer accepts or `--max-rounds` (3) review
   rounds are spent. The reviewer's decision picks the next step: repair the code, repair the plan, or accept.
3. **FINISH** — writes `run-report.md`, prints it, and commits if `--commit` was given.

Outcomes: `DONE`, `DONE_PARTIAL` (placeholders left), `BLOCKED`, `RED`, `ESCALATED` (round limit reached or a human decision is needed). Commit your production code first — a dirty target is always BLOCKED.

## Configuration

Per-repository settings live in the **project directory** `.github/agents/tc-agent-project/`,
never inside this package. All files are optional; all keys: `docs/configuration.md`.

- **`profile.md`** (json block): gates (`branch_coverage_target_scope` 0.80,
  `mutation_score_target_scope` 0.70), `max_rounds` (3), `freshness_days` (7),
  `protected_branches` (default `["master", "main"]`), `instruction_paths`, `test_data_paths`,
  `junit`, `tooling`, and the maven keys (`maven_timeout_seconds`, `maven_also_make`,
  `maven_skip_main_compile`, `maven_goals_only`, `maven_args`, `maven_snapshot_updates`).
- **`conventions.md`** — this repo's test style; read first among the style rules.
- **`test-data-examples.md`** — example business values; always in the context pack.
- **Other style rules** — `.github/copilot-instructions.md`, `.github/instructions/*.instructions.md`
  (by `applyTo`) and `AGENTS.md`. Repo rules override the default style in
  `references/conventions.md` §B, never §A.

Default style: `shouldXxxWhenYyy`, `// given / // when / // then`, AssertJ, Mockito for repositories, class under test as a field, class `<Target>Test`.

## Commit (`--commit`)

- Only on `DONE` or `DONE_PARTIAL`, and only the test files this run wrote.
- On a protected branch it first creates a new branch `tc-agent/<target>/<run-id>`.
- Message: title `[TC-AGENT] Add tests for <target>.`, a 2–5 sentence summary of the whole run
  (written by the reviewer), then facts (mode, target sha, counts, gates, suggestions) — nothing from `.test-agent/`.
- Never pushes.

## What you get

Every run has its own folder `.test-agent/runs/<target>/<run-id>/`:
`run.json`, `derive-state.md`, `context-pack.md`, `plan-vN.md`,
`generation-report-vN[-rM].md`, `review-vN-rM.md`, `checks/`, `run-report.md`. Old runs are never read again and never deleted.
Each generated test method has a two-line Javadoc:

    AI-generated test. Characterizes current behavior of SimpleCalculatorService (a freeze, not a spec).
    tc-agent-mode: characterization, interactive: false

What the test froze is the code at the test's own last commit — git has it.

A scenario that cannot be tested (e.g. code reads `LocalDateTime.now()`) becomes an empty
`@Disabled("AI deferred: …")` method with `tc-agent-deferred: <reason>`. Do not delete
placeholders — they tell the next run the gap is known.

## Good to know

- Only the scripts run Maven; the agents never do; to start again, just run again.
- In PowerShell, quote `-D` args: `mvn "-Dtest=FooTest"`.

## Files

You edit only the project directory. Everything in `tc-agent/` is the agent itself: on an
update, replace the folder as a whole. No agent reads this README.

**`tc-agent-project/` — this repository's settings (all optional)**

| file | what it is |
|---|---|
| `profile.md` | gates, rounds, freshness, protected branches, maven; every key in `docs/configuration.md` |
| `conventions.md` | your test style; overrides the default style, never the fixed rules |
| `test-data-examples.md` | example business values: what an id or an account number looks like |
| `README.md` | what belongs in this folder |

**`tc-agent/` — the agent**

| file | what it is |
|---|---|
| `README.md` | this file |
| `requirements.txt` | the only Python dependency, `jsonschema` |
| `docs/configuration.md` | every `profile.md` key with its default |
| `docs/architecture.svg` | the diagram at the top |
| `tc-orchestrator.agent.md` | the agent you call: runs the scripts, hands work to the other agents, shows the report |
| `tc-planner.agent.md` | decides what to test and with which data; writes the plan |
| `tc-generator.agent.md` | writes the tests and placeholders the plan asks for |
| `tc-reviewer.agent.md` | runs tests, coverage and mutations, judges the tests, accepts or sends them back |
| `references/contracts.md` | rules for every agent: run files, rounds, which rule wins |
| `references/conventions.md` | how tests are written: fixed rules (metadata, data, determinism) and the default style |
| `references/junit4.md` | what differs in a JUnit 4 module |
| `references/modes/characterization.md` | what freezing the current behavior means for each agent |
| `references/modes/spec-driven.md` | what testing only the specification means for each agent |
| `references/modes/interactive.md` | when and what the planner asks you |
| `schemas/*.schema.json` | the shape of the plan, the generator's report, the review and `profile.md` |
| `scripts/tc_orchestrate.py` | the state machine: `start`, `state`, `finish`; round limit, report, commit |
| `scripts/tc_derive_state.py` | at start: what the target needs (git, tests, coverage, mutations) |
| `scripts/tc_build_context.py` | builds the context pack the planner and the generator read |
| `scripts/tc_run_tests.py` | runs the target's tests with JaCoCo; the only script that builds |
| `scripts/tc_coverage.py` | branch coverage of the target against the gate; uncovered lines |
| `scripts/tc_mutation.py` | PIT on the target only; surviving mutants against the gate |
| `scripts/tc_javadoc.py` | reads the `tc-agent-*` lines of generated tests |
| `scripts/tc_git.py` | git facts: sha, uncommitted changes, commit age, changed lines |
| `scripts/tc_common.py` | shared code: finding the target and its module, the profile, maven calls |
| `scripts/tc_evidence_strength.py` | grades the evidence of each planned scenario |
| `scripts/tc_verify_refs.py` | checks that every reference in a plan points at real lines |
| `scripts/tc_validate_plan.py` | checks a plan, report or review against its schema |
| `scripts/tc_md_payload.py` | reads and writes the json block inside the run's `.md` files |
