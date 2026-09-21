# Test conventions (tc-agent)

Repo-agnostic conventions for every test this pipeline writes or reviews. They
travel with the agent, so they apply in any repository — a repository does not
need an AGENTS.md or any other file for the agent to work correctly.

Precedence, rule by rule:

    §A pipeline integrity  >  repo instructions (REPO CONVENTIONS in the context pack)  >  §B defaults

A repo instruction may replace any §B rule. It can never relax an §A rule; when
it tries, follow §A and mention the conflict in your artifact's `notes`.

## §A — Pipeline integrity (not overridable)

**A1. Metadata.** Every test method you write carries a Javadoc: one prose line,
a blank line, then one `tc-agent` metadata line per fact. Metadata goes on
METHODS only — never on the test class, not even when the whole class is yours.

```java
/**
 * AI-generated test. Characterizes current behaviour of OrderService (a freeze, not a spec).
 *
 * tc-agent: generated
 * tc-agent-mode: legacy
 * tc-agent-characterizes: OrderService@29aeef6a
 */
```

| line | when |
|---|---|
| `tc-agent: generated` | always |
| `tc-agent-mode: legacy` / `tc-agent-mode: spec-driven` | always — from `run.json` |
| `tc-agent-interactive: true` | when `run.json` says `interactive: true` |
| `tc-agent-characterizes: <Class>@<sha>` | legacy only; `<sha>` = the plan's `context.target_sha`, `<Class>` = the target class |
| `tc-agent-deferred: <reason>` | placeholders only (A2) |
| `tc-agent-note: <text>` | optional, repeatable, about THIS test (a frozen known bug, a human's answer) |

First prose line:
- legacy: `AI-generated test. Characterizes current behaviour of <Class> (a freeze, not a spec).`
- spec-driven: `AI-generated test. Based on a specification provided at generation time (not stored in the repo).`
- placeholder: `AI-generated placeholder. Scenario deliberately NOT tested — see tc-agent-deferred.`

Never add these lines to a method you did not write, and never remove them from
one you repair.

They are plain text lines, not Javadoc `@tags`: no IDE or doclint flags them,
and the scripts read them with a fixed pattern (`tc-agent-<key>: <value>`, one
per line, lowercase key, a colon, a space). Never write them as `tc-agent: generated`,
`tc-agent-mode` … — that is an old draft format the scripts report as a defect.

**A2. Placeholders.** A scenario that is deferred, or that cannot be implemented
soundly — no code seam, a value with no evidence, a compile error you could not
fix — becomes an empty, disabled method:

```java
/**
 * AI-generated placeholder. Scenario deliberately NOT tested — see tc-agent-deferred.
 *
 * tc-agent: generated
 * tc-agent-mode: legacy
 * tc-agent-characterizes: AppointmentService@29aeef6a
 * tc-agent-deferred: business-hours guard reads LocalDateTime.now() directly; needs an injected java.time.Clock
 */
@Test
@Disabled("AI deferred: needs a Clock seam")
@DisplayName("appointment outside business hours is rejected")
void shouldRejectAppointmentWhenOutsideBusinessHours() {
}
```

- the body is empty (no comments needed, no given/when/then);
- the `@Disabled` text starts with `AI deferred:`;
- `tc-agent-deferred` carries the full reason; for a compile error, quote the compiler
  message;
- **every plan scenario ends up in the code as a test OR a placeholder.** A
  placeholder is the only record that a gap is known and deliberate — without
  it the next run sees an unexplained gap and plans it again.

**A3. Characterization.** A legacy test freezes what the code did at `<sha>`,
bugs included. It asserts current behaviour, never what you think is correct.
When a human (interactive) said the behaviour is a defect, still assert the
current behaviour and add `tc-agent-note: reported as defect: <what>`.

**A4. Data.** Every business value comes from the plan's evidence: builders,
fixtures, seeders, existing tests, or — in legacy — the code under test itself.
No invented names, amounts, ids, statuses.

**A5. Determinism.** No test may depend on the wall-clock time, the date, random
values, execution order or sleeps.
- When production code reads the clock directly (no injected `Clock`), build
  times RELATIVE to now and make them satisfy every guard that precedes the one
  under test (the thresholds come from the plan's evidence).
- When a branch cannot be made deterministic without a code seam, write a
  placeholder (A2) and a suggestion such as "inject java.time.Clock and use
  LocalDateTime.now(clock)". A flaky test is the worst possible output.

**A6. Boundaries.** Never modify production code. Never mock the class under
test. Never delete a test — recommend it instead.

**A7. One scenario, one method.** A parameterized test may cover sibling
scenarios of the same shape; list each covered scenario's description in a
`tc-agent-note`.

## §B — Defaults (a repo instruction may replace any of these)

**B1. Method names:** lowerCamelCase `should<Outcome>When<Condition>`, no
underscores, no `test` prefix.

    shouldThrowNotFoundWhenOfferDoesNotExist
    shouldSaveScheduledAppointmentWhenRequestIsValid
    shouldReturnAllActiveOffers                 (no meaningful condition)

This applies to new methods even in a class whose existing (human) methods use
another style: only an explicit repo instruction changes the rule.

**B2. `@DisplayName`:** the scenario description, in plain English.

**B3. Structure:** three commented sections, separated by a blank line.

```java
// given
CreateAppointmentRequest request = validRequest();

// when
AppointmentResponse response = service.create(request);

// then
assertThat(response.status()).isEqualTo(AppointmentStatus.SCHEDULED);
```

When act and assert are one statement (an exception assertion):

```java
// when & then
assertThatThrownBy(() -> service.create(request))
    .isInstanceOf(ApiException.class)
    .extracting("status").isEqualTo(HttpStatus.NOT_FOUND);
```

A section with nothing in it is left out (a test with no arrangement starts at
`// when`). Placeholders (A2) have no sections.

**B4. Assertions:** AssertJ when it is on the classpath, otherwise JUnit 5
assertions. An exception assertion checks the type AND the property that tells
it apart (status, code, message) — never a bare "throws". Not `assertNotNull`
alone, not `verify` alone.

**B5. Collaborators:** mock the classes that stand for a database or a network
boundary (repositories, gateways, clients) with Mockito; build real domain
objects, DTOs and value types.

**B6. Setup:** extract a private helper for construction repeated across tests
(`validRequest()`, `activeOffer()`) instead of repeating it.

**B7. Test class:** `<Target>Test` in the target's package under the test root,
unless a test class for the target already exists — then add to that one.
