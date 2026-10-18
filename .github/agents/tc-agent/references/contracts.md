# Shared contracts

Rules every role of the test pipeline follows. Your role prompt adds only what is
special about your role.

## 0. Where the truth lives

**The truth is the committed code, the tests and git history.** Nothing the
pipeline writes to `.test-agent/` is ever read as state by a later run.

- Between runs, `tc_orchestrate.py start` derives what a target needs from the
  code, the test methods and their `tc-agent-` metadata, git, coverage and
  mutations (`tc_derive_state.py`).
- Inside one run, the roles hand work to each other through files in that run's
  directory, `.test-agent/runs/<target>/<run-id>/`. Never read, cite or continue
  from another run's directory.

## 1. What you read, and in which order of authority

`dispatch.references` lists the instruction files for THIS run: read every one,
in order, before anything else, and no other file under `references/`. In a file
with role sections, yours is the section named after your role. `mode`,
`interactive`, `spec` and `max_rounds` live in the run's `run.json`; nobody
passes them in the prompt.

Precedence, rule by rule:

1. **pipeline integrity** — this file, `conventions.md` §A, `junit4.md` and the
   mode files. Never overridable: a repo instruction that contradicts them is
   void; follow them and say so in your artifact's notes.
2. **repo instructions** — the REPO CONVENTIONS section of the context pack.
   Style and technique only, never evidence about business behavior.
3. **agent defaults** — `conventions.md` §B.

## 2. Artifacts

Every artifact is a Markdown file: a title, a SHORT summary for a human, and
EXACTLY ONE fenced ```json block. The JSON is the contract; when the prose
disagrees, the prose is the defect. Write the file with your file-writing tool,
as UTF-8, and change it only with your file-editing tool — never through a
script or shell redirection (`>`, `Out-File`, `Set-Content`), which on Windows
mangles characters such as `—`. Strict JSON: double quotes, no trailing commas,
no comments, never a second ```json fence. Any fenced block holds valid content of
its language: ```java only compilable Java, never with line numbers — quote
numbered code as ```text.

| artifact (in the run directory) | written by | schema (`$SCH` = `.github/agents/tc-agent/schemas`) |
|---|---|---|
| `run.json` | `tc_orchestrate.py start` | — (mode, interactive, spec, max_rounds, commit) |
| `derive-state.md` | `tc_derive_state.py` | — (read it, never edit it) |
| `context-pack.md` | `tc_build_context.py` | — |
| `plan-v<N>.md` | tc-planner | `$SCH/tc-test-plan.schema.json` |
| `generation-report-v<N>[-r<M>].md` | tc-generator | `$SCH/tc-generation-report.schema.json` |
| `review-v<N>-r<M>.md` | tc-reviewer | `$SCH/tc-review.schema.json` |
| `checks/*-<label>.md` | check scripts | — |
| `run-report.md` | `tc_orchestrate.py finish` | — |

Validate before you finish:

    python .github/agents/tc-agent/scripts/tc_validate_plan.py <file> <schema>

A validator reports a defect in YOUR artifact, and the only answer is to fix the
field it names. Never delete a field, drop a scenario, strip evidence or make a
value vaguer to make a check pass — that hides the defect.

## 3. Rounds and numbering

`state` names the exact file to write (`dispatch`). One review closes one round;
a run has at most `max_rounds` of them (default 3), a new plan version included.

| file | when the number grows |
|---|---|
| `plan-v<N>.md` | N + 1 when the reviewer asks for REPAIR_PLAN |
| `generation-report-v<N>.md` | first round of a plan; repair rounds add `-r2`, `-r3` |
| `review-v<N>-r<M>.md` | M matches the generation round it reviews |

Never overwrite an artifact of the run; write the next number.

## 4. The code is the database

Every test the pipeline writes carries its metadata as `tc-agent-<key>: <value>`
lines in the Javadoc of the test METHOD — format in `conventions.md` §A1,
placeholders in §A2.

- **Invariant:** every scenario of a plan ends up in the code as a test OR as a
  placeholder. A placeholder is how the next run knows a gap is deliberate.
- **Traceability:** a scenario id (`TC01`) exists only in the run's artifacts,
  never in the code. Scenario and test are linked by the method name
  (`implementation_hints.test_method` ↔ `results[].test_method`).
- **Stale** = a characterization test whose `tc-agent-characterizes` sha no
  longer names the last commit of the target. Still green: a script moves the
  sha (`reseal`). Red: it goes back to the planner.

## 5. The context pack

`<run_dir>/context-pack.md` (built by `tc_build_context.py`) is the main source
about the repository: TEST FRAMEWORK, TEST DATA, DATA EXAMPLES (how tests
anywhere in the repo fill the fields this target uses), REPO CONVENTIONS, the
target, its existing tests, builders, enums and dependencies. Every source block
shows the FILE's own line numbers in its left column: a ref (`path:NN`) comes
from that column, never from counting lines of the pack.

A type the pack does not contain is never a reason to defer a scenario. Classes
from a dependency jar are listed under TYPES FROM DEPENDENCIES, generated code
appears as GENERATED SOURCE; build such a value the way the target or an
existing test builds it and cite that line. A missing signature is a lookup
problem, not untestable behavior.

## 6. Scripts

Run them with the plain `python` on PATH (`python3` where that is its name). One
dependency, `jsonschema`, for the validators:
`pip install -r .github/agents/tc-agent/requirements.txt`. Maven only; every
check script drives `mvn` and roles never run `mvn` themselves.

| exit code | meaning |
|---|---|
| 0 | the check ran, the gate is met |
| 1 | the check ran, it found a defect |
| 2 | the check could NOT run (tooling or environment) — never a pass |

**A script is a black box:** your contract with it is the command, the exit code
and the report it writes. Never open its source; a script that behaves
unexpectedly is something to report, not to debug.

**PowerShell:** quote a whole `-Dkey=value` argument that contains dots:
`"-Dtest=com.acme.OrderServiceTest"`. The scripts quote for you.
