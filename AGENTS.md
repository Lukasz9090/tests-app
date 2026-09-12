# Test instructions

Conventions for tests in this repository. Agents read this file through the
context pack, in its CONVENTIONS section; people read it directly.

These are conventions of style and technique. They are NOT evidence about
business behaviour: every expected value in a test still has to come from the
plan's evidence.

## Marking generated tests

Whenever you create a new test method, add the following comment immediately
before the test method:

// AI GENERATED

Do not add this comment to existing tests that you are only modifying.

## Characterization tests

A test generated from a characterization plan also carries:

// CHARACTERIZATION: freezes <Class> @ <sha> (current behaviour, not a spec)

Read it as a warning, not as a requirement. Such a test records what the code did
at that commit, bugs included; nobody confirmed the behaviour is correct. When it
fails after a change, the first question is whether the old behaviour was right —
not how to make the test green again.

## Time and determinism

Production code calls `LocalDateTime.now()` directly and there is no injected
Clock, so a test that hardcodes a date will pass today and fail next month.
Build test times RELATIVE to now, so that the guards evaluate the same way on
every run:

- "less than 2h notice" → a quarter-aligned time about now+30min;
- "beyond 90 days" → now+91 days at a valid business hour;
- align to the 15-minute grid and to business hours whenever the guard under
  test needs the earlier guards to pass first.

The thresholds themselves (the notice period, the horizon, the opening hours)
come from the plan's evidence, not from this file. What this file fixes is how
you express them: always relative to now, never as a literal timestamp.

Never write a test whose result depends on the wall-clock time of the run.
