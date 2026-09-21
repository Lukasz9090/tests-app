# Shared contracts (Model B)

Rules that all four agents of the test pipeline follow. Read this before your
own agent file. Your agent file only adds what is special about your role.

## 0. Where the truth lives

**The truth is the committed code, the tests and git history.** Nothing the
pipeline writes to `.test-agent/` is ever read as state by a later run.

- Between runs, `tc_orchestrate.py start` derives what a target needs from the
  real world (`tc_derive_state.py`): the code, the test methods and their
  Javadoc tags, git, coverage and mutations.
- Inside one run, the roles hand work to each other through files in that
  run's directory, `.test-agent/runs/<slug>/<run-id>/`. Never read, cite or
  continue from another run's directory. Old runs stay on disk for people only.

## 1. Artifacts

Every artifact is a Markdown file with three parts:

1. a title,
2. a SHORT summary for a human,
3. EXACTLY ONE fenced ```json block.

The JSON block is the contract and the prose is not: when they disagree, the
JSON is right and the prose is the defect to fix. Write strict JSON — double
quotes, no trailing commas, no comments, never a second fence. (The container is
Markdown because org policy blocks .json and .yaml files for Copilot.)

| artifact (in the run directory) | written by | schema |
|---|---|---|
| `run.json` | `tc_orchestrate.py start` | — (mode, interactive, spec, caps, commit) |
| `derive-state.md` | `tc_derive_state.py` | — (read it, never edit it) |
| `context-pack.md` | `tc_build_context.py` | — |
| `plan-v<N>.md` | tc-planner | `$SCH/tc-test-plan.schema.json` |
| `generation-report-v<N>[-r<M>].md` | tc-generator | `$SCH/tc-generation-report.schema.json` |
| `review-v<N>-r<M>.md` | tc-reviewer | `$SCH/tc-review.schema.json` |
| `checks/*-<label>.md` | check scripts | — |
| `run-report.md` | `tc_orchestrate.py finish` | — |

`$SCH` = `.github/agents/tc-agent/schemas`, `$C` = `.github/agents/tc-agent/scripts`.

`run.json` is where `mode`, `interactive` and `spec` live. Read them from there;
nobody passes them to you in the prompt.

Validate before you finish:

```
python .github/agents/tc-agent/scripts/tc_validate_plan.py <file> <schema>
```

The tool reports defects in YOUR artifact, and there is one correct answer: fix
the field it names. Never delete a field, drop a scenario or make a value vaguer
to make the check pass, because that hides the defect instead of fixing it.

## 2. Numbering inside a run

The orchestrator's `state` tells you the exact path to write (`dispatch`). The
numbers exist only to count rounds against the caps:

| file | when the number grows |
|---|---|
| `plan-v<N>.md` | N + 1 when the reviewer asks for REPAIR_PLAN |
| `generation-report-v<N>.md` | first round; repair rounds add `-r2`, `-r3` |
| `review-v<N>-r<M>.md` | M matches the generation round it reviews |

Never overwrite an artifact of the run; write the next number.

## 3. The code is the database

Every test the pipeline writes carries its metadata in a Javadoc on the test
METHOD (never on the class). The full rules are in `tc-test-conventions.md` §A;
the tags are:

| tag | meaning |
|---|---|
| `@aiGenerated` | the agent wrote this method |
| `@mode legacy` / `@mode spec-driven` | how it was generated |
| `@interactive` | a human answered questions during that run |
| `@characterizes <Class>@<sha>` | legacy only: the version of the code this test froze |
| `@deferred <reason>` | on an `@Disabled` placeholder: a scenario deliberately not tested |
| `@note <text>` | a frozen known bug or a human decision about THIS test |

**Invariant:** every scenario of a plan ends up in the code as a test OR as a
placeholder. That is how the next run knows a gap is known and deliberate.

**Traceability:** a scenario id (`TC01`) exists only inside the run's
artifacts. It never goes into the code. A scenario and its test are linked by
the method name: `implementation_hints.test_method` in the plan,
`results[].test_method` in the generation report.

**Stale** = a legacy test whose `@characterizes` sha no longer names the last
commit of the target file (or the target has uncommitted changes). A stale test
that still passes only needs its sha moved (`reseal`, done by a script); a
stale test that fails means the frozen behaviour changed and goes back to the
planner.

## 4. Scripts

Run every script with the plain `python` on PATH (`python3` where that is its
name). There is one dependency, `jsonschema`, used by `tc_validate_plan.py`:
`pip install -r .github/agents/tc-agent/tc-requirements.txt`. Everything else
is standard library, so there is no virtualenv to set up.

This pipeline supports **Maven only**. Every check script drives `mvn`.

Check scripts use these exit codes:

| code | meaning |
|---|---|
| 0 | the check ran, the gate is met |
| 1 | the check ran, it found a defect |
| 2 | the check could NOT run (tooling or environment) |

Exit 2 is never a pass.

**A script is a black box.** Your whole contract with one is the command you
run, the exit code it returns and the report it writes. Never open a script's
source. It tells you nothing the report does not, it spends the context you need
for the plan and the tests, and it invites you to reason about how a check works
instead of acting on what it found. A script that behaves unexpectedly is
something to report, not something to debug.

## 5. Conventions

Before you write or judge a test, read `.github/agents/tc-agent/tc-test-conventions.md`
and the **REPO CONVENTIONS** section of the run's `context-pack.md`.

Precedence, rule by rule:

1. **pipeline integrity** — this file and `tc-test-conventions.md` §A. Never
   overridable. A repo instruction that contradicts it is void; follow §A and
   say so in your artifact's notes.
2. **repo instructions** — the files listed in REPO CONVENTIONS.
3. **agent defaults** — `tc-test-conventions.md` §B.

Repo instructions are about style and technique. They are never evidence about
business behaviour.
