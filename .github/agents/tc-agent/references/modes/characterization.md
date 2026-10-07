# Mode: characterization

The oracle is the CURRENT code. A characterization test freezes what the code did
at a commit, bugs included: it asserts current behavior, never what you think is
correct. When a human said a behavior is a defect, the test still asserts it and
carries `tc-agent-note: reported as defect: <what>`.

## Planner

- Set top-level `characterization: true` and copy `git.current_sha` from
  `derive-state.md` into `context.target_sha`.
- The target's own lines are legitimate evidence (`type: implementation`): a
  scenario that asserts what the code demonstrably does needs no second source,
  and a value the code defines (a boundary, a constant, a status it switches on)
  is taken from the code (`conventions.md` §A4). Only an identity-like value with
  no known shape can defer a scenario — and only when its meaning decides the branch.
- Never describe frozen behavior as correct business behavior.
- **Stale entries** (`recharacterize` in `derive-state.md`):
  - a stale test that FAILS — the frozen behavior changed: plan a scenario that
    freezes the NEW behavior with `replaces: <Class>#<method>` (keep the name
    unless it now lies), say in the description what changed, and add a `notes`
    entry `behavior changed at <sha>: was X, now Y` when it looks like a regression;
  - a stale placeholder — re-evaluate it: a seam or new evidence appeared → a
    scenario with `replaces: <placeholder>`; otherwise a `deferred` entry with the
    same `replaces` and `placeholder_method`, so its sha is refreshed.
- **Placeholders that are not stale** are known, deliberate gaps: plan them again
  only with NEW evidence (then `replaces`).
- **Obsolete tests** (the behavior is gone from the code): list them in `obsolete`
  with the reason; never plan their deletion.

Example (`context.test_data` shows the shape of a human answer):

```json
{
  "schema_version": 1,
  "plan_version": 1,
  "target": { "class": "AppointmentService" },
  "mode": "characterization",
  "interactive": false,
  "characterization": true,
  "status": "READY_PARTIAL",
  "context": {
    "existing_tests": ["AppointmentServiceTest#shouldRejectPastStartTimeWhenCreating"],
    "target_sha": "4b1c2aa9",
    "test_data": [
      { "concept": "customer id", "rule": "9 digits", "examples": ["123456789", "987654321"],
        "applies_to": ["ownerCustomerId", "coownerCustomerId"], "used_by": ["TC01"] }
    ],
    "notes": ["scope: COVERAGE_GAP lines 88, 112"]
  },
  "scenarios": [
    {
      "id": "TC01",
      "description": "a request for an inactive offer is rejected with 409",
      "priority": "high",
      "evidence_strength": "medium",
      "data": { "offer": { "source": "seeder", "ref": "src/main/java/com/testsapp/bootstrap/DataSeeder.java:18" } },
      "implementation_hints": {
        "test_method": "shouldRejectAppointmentWhenOfferIsInactive",
        "test_file": "src/test/java/com/testsapp/service/AppointmentServiceTest.java"
      },
      "evidence": [ { "type": "implementation", "ref": "src/main/java/com/testsapp/service/AppointmentService.java:86-90" } ]
    },
    {
      "id": "TC02",
      "description": "reschedule keeps the original duration (behavior changed at 4b1c2aa9)",
      "priority": "high",
      "evidence_strength": "medium",
      "replaces": "AppointmentServiceTest#shouldKeepDurationWhenRescheduling",
      "notes": ["behavior changed at 4b1c2aa9: duration used to be recomputed from the offer"],
      "implementation_hints": {
        "test_method": "shouldKeepDurationWhenRescheduling",
        "test_file": "src/test/java/com/testsapp/service/AppointmentServiceTest.java"
      },
      "evidence": [ { "type": "implementation", "ref": "src/main/java/com/testsapp/service/AppointmentService.java:140-152" } ]
    }
  ],
  "deferred": [
    {
      "id": "TC03",
      "description": "an appointment outside business hours is rejected",
      "reason": "the business-hours guard reads LocalDateTime.now() directly; no deterministic test without an injected Clock",
      "placeholder_method": "shouldRejectAppointmentWhenOutsideBusinessHours",
      "test_file": "src/test/java/com/testsapp/service/AppointmentServiceTest.java",
      "evidence_strength": "medium",
      "evidence": [ { "type": "implementation", "ref": "src/main/java/com/testsapp/service/AppointmentService.java:112" } ]
    }
  ],
  "obsolete": []
}
```

## Generator

- First Javadoc line: `AI-generated test. Characterizes current behavior of <Class> (a freeze, not a spec).`
- Metadata (`conventions.md` §A1): `tc-agent-mode: characterization, interactive: <run.json>`
  and `tc-agent-characterizes: <TargetClass>@<plan.context.target_sha>` — on
  tests AND placeholders. A rewritten method (`replaces`) gets the new sha.

## Reviewer

- Stage 1: every method this run wrote carries `tc-agent-characterizes:
  <TargetClass>@<sha>` with the plan's `context.target_sha`.
- A failing assertion in a test this run wrote is **REPAIR_IMPLEMENTATION** —
  unless the plan misread the code and the expectation itself is wrong:
  **REPAIR_PLAN**. A failing test this run did NOT touch (human, or older AI) is
  **NEEDS_TRIAGE**: something outside this run broke it.
