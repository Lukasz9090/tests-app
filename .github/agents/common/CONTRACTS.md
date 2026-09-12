# Shared contracts

Rules that all four agents of the test pipeline follow. Read this before your
own agent file. Your agent file only adds what is special about your role.

## 1. Artifacts

Every artifact is a Markdown file with three parts:

1. a title,
2. a SHORT summary for a human,
3. EXACTLY ONE fenced ```json block.

The JSON block is the contract and the prose is not: when they disagree, the
JSON is right and the prose is the defect to fix. Write strict JSON — double
quotes, no trailing commas, no comments, never a second fence. (The container is
Markdown because org policy blocks .json and .yaml files for Copilot.)

Each artifact has a schema, and the schema is the contract — an example is only
an example.

| artifact | schema |
|---|---|
| `plan-v<N>.md` | `test-planner/schemas/test-plan.schema.json` |
| `generation-report-v<N>[-r<M>].md` | `test-generator/schemas/generation-report.schema.json` |
| `review-v<N>-r<M>.md` | `test-reviewer/schemas/review.schema.json` |

Validate before you finish:

```
python .github/agents/common/scripts/validate_plan.py <file> <schema>
```

The tool reports defects in YOUR artifact, and there is one correct answer: fix
the field it names. Never delete a field, drop a scenario or make a value vaguer
to make the check pass, because that hides the defect instead of fixing it.

## 2. File names and versions

All artifacts live in `.test-agent/plans/<TargetSlug>/`. `<TargetSlug>` is
`ClassName` or `ClassName.methodName`.

| file | when the number grows |
|---|---|
| `plan-v<N>.md` | N + 1 for each new plan version |
| `generation-report-v<N>.md` | first round; later rounds add `-r2`, `-r3` |
| `review-v<N>-r<M>.md` | M matches the generation round it reviews |

NEVER overwrite or delete an artifact; write the next version instead, because
the file history is how a run is resumed and audited.

## 3. The two scenario axes

Every scenario carries two flags that are independent of each other, and one can
never stand for the other.

| field | the question it answers | values |
|---|---|---|
| `change` | did the scenario DEFINITION change since `based_on_version`? | `NEW` / `MODIFIED` / `UNCHANGED` / `REMOVED` |
| `implementation` | does a test for it exist? | `PENDING` / `COVERED` / `BLOCKED` |

`REMOVED` means the BEHAVIOUR is gone, because the code path was deleted or the
requirement was withdrawn. A test for it is now a deletion candidate, so
`change_reason` is required and must name that cause.

`REMOVED` NEVER means "already implemented", "already covered by a passing test"
or "nothing to do here". That is `implementation: COVERED`, with `covered_by`
naming the test, while `change` stays `UNCHANGED` or `MODIFIED`.

Pick the label for what it MEANS, never for what it makes the next agent skip:
a person who reads `REMOVED` will delete a working test.

## 4. Scripts

Run every script with the plain `python` on PATH (`python3` where that is its
name). There is one dependency, `jsonschema`, used by `validate_plan.py`:
`pip install -r .github/agents/requirements.txt`. Everything else is standard
library, so there is no virtualenv to set up.

This pipeline supports **Maven only**. Every check script drives `mvn`.

Check scripts use these exit codes:

| code | meaning |
|---|---|
| 0 | the check ran, the gate is met |
| 1 | the check ran, it found a defect |
| 2 | the check could NOT run (tooling or environment) |

Exit 2 is never a pass.
