# Test conventions (tc-agent)

Repo-agnostic conventions for every test this pipeline writes or reviews. They
travel with the agent, so they apply in any repository — a repository does not
need an AGENTS.md or any other file for the agent to work correctly.

Precedence, rule by rule:

    §A pipeline integrity  >  repo instructions (REPO CONVENTIONS in the context pack)  >  §B defaults

A repo instruction may replace any §B rule. It can never relax an §A rule; when
it tries, follow §A and mention the conflict in your artifact's `notes`.

## §A — Pipeline integrity (not overridable)

**A0. The test framework is the repo's, not a default.** The run's
`derive-state.md` carries `repo.junit` (`"5"`, `"4"` or null) and the context
pack repeats it as TEST FRAMEWORK. Write every test with the annotations and
assertions of THAT version, and never add a dependency to make your favorite
one available. Where a rule below differs, it says "JUnit 5" and "JUnit 4"
explicitly. Both present (JUnit 4 plus the vintage engine) counts as JUnit 5.
When the pack says the framework is unknown, follow the existing test class;
with no test class either, write JUnit 5 and say so in your artifact's `notes`.

**A1. Metadata.** Every test method you write carries a Javadoc: one prose line,
a blank line, then one `tc-agent` metadata line per fact. Metadata goes on
METHODS only — never on the test class, not even when the whole class is yours.

```java
/**
 * AI-generated test. Characterizes current behavior of OrderService (a freeze, not a spec).
 *
 * tc-agent-mode: legacy, interactive: false
 * tc-agent-characterizes: OrderService@29aeef6a
 */
```

| line | when |
|---|---|
| `tc-agent-mode: <mode>, interactive: <true\|false>` | always — both values from `run.json`; the mode is `legacy` or `spec-driven` and `interactive` is always written, also when it is false |
| `tc-agent-characterizes: <Class>@<sha>` | legacy only; `<sha>` = the plan's `context.target_sha`, `<Class>` = the target class |
| `tc-agent-deferred: <reason>` | placeholders only (A2) |
| `tc-agent-note: <text>` | optional, repeatable, about THIS test (a frozen known bug, a human's answer) |

First prose line:
- legacy: `AI-generated test. Characterizes current behavior of <Class> (a freeze, not a spec).`
- spec-driven: `AI-generated test. Based on a specification provided at generation time (not stored in the repo).`
- placeholder: `AI-generated placeholder. Scenario deliberately NOT tested — see tc-agent-deferred.`

Never add these lines to a method you did not write, and never remove them from
one you repair.

They are plain text lines, not Javadoc `@tags`: no IDE or doclint flags them,
and the scripts read them with a fixed pattern (`tc-agent-<key>: <value>`, one
per line, lowercase key, a colon, a space). Never write them as `@aiGenerated`,
`@mode` … — that is an old draft format the scripts report as a defect. The
separate `tc-agent: generated` and `tc-agent-interactive: true` lines are an
older shape: still read, never written again.

**A2. Placeholders.** A scenario that is deferred, or that cannot be implemented
soundly — no code seam, a value with no evidence, a compile error you could not
fix — becomes an empty, disabled method:

```java
/**
 * AI-generated placeholder. Scenario deliberately NOT tested — see tc-agent-deferred.
 *
 * tc-agent-mode: legacy, interactive: false
 * tc-agent-characterizes: AppointmentService@29aeef6a
 * tc-agent-deferred: business-hours guard reads LocalDateTime.now() directly; needs an injected java.time.Clock
 */
@Test
@Disabled("AI deferred: needs a Clock seam")          // JUnit 4: @Ignore("AI deferred: needs a Clock seam")
@DisplayName("appointment outside business hours is rejected")   // JUnit 5 only
void shouldRejectAppointmentWhenOutsideBusinessHours() {
}
```

- the body is empty (no comments needed, no given/when/then);
- the disabling annotation is `@Disabled` in JUnit 5 and `@Ignore` in JUnit 4,
  and its text starts with `AI deferred:`;
- `tc-agent-deferred` carries the full reason; for a compile error, quote the compiler
  message;
- **every plan scenario ends up in the code as a test OR a placeholder.** A
  placeholder is the only record that a gap is known and deliberate — without
  it the next run sees an unexplained gap and plans it again.

**A3. Characterization.** A legacy test freezes what the code did at `<sha>`,
bugs included. It asserts current behavior, never what you think is correct.
When a human (interactive) said the behavior is a defect, still assert the
current behavior and add `tc-agent-note: reported as defect: <what>`.

**A4. Data.** Every business value comes from the plan's evidence: builders,
fixtures, seeders, existing tests, or — in legacy — the code under test itself.
No invented names, amounts, ids, statuses.

Two things are NOT business data and never make a scenario a placeholder:
- **Relational values** — a value whose only role is to be equal (or not
  equal) to another value the test also controls: a key compared with the key
  of an entry a mock returns, an id passed in and echoed back. Any neutral
  literal works (`"KEY-1"` / `"OTHER-KEY"`); the evidence is the comparison
  line in the code under test. Name them so nobody reads them as real data.
- **Object shapes** — a DTO or domain object built with its own constructor,
  builder or setters. The class declaration is the evidence for its shape;
  fill only the fields the code under test reads.

Only a value whose MEANING matters (a real status the code switches on, a
threshold, an IBAN format) needs a source beyond that.

When the plan carries such a value — from an existing test, a builder or a
human's answer in an interactive run — it comes with a SHAPE (`customer id: 9
digits, e.g. 123456789`). Use the shape, not one literal: every field of that
kind (`ownerCustomerId`, `coownerCustomerId`) and every distinct entity in a
test gets its OWN value matching it, never one id for two parties and never a
value the rule does not allow. An id that looks real tells the next reader what
the system expects, and the test becomes the record of that shape.

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

**A7. One scenario, one method.** In JUnit 5 a parameterized test may cover
sibling scenarios of the same shape; list each covered scenario's description in
a `tc-agent-note`. In JUnit 4 do NOT parameterize: `@RunWith(Parameterized)`
takes over the whole class, so write one plain method per scenario.

## §B — Defaults (a repo instruction may replace any of these)

**B1. Method names:** lowerCamelCase `should<Outcome>When<Condition>`, no
underscores, no `test` prefix.

    shouldThrowNotFoundWhenOfferDoesNotExist
    shouldSaveScheduledAppointmentWhenRequestIsValid
    shouldReturnAllActiveOffers                 (no meaningful condition)

The outcome names the operation, so that tests of sibling methods never share
a name: `shouldReportEvenWhenNumberIsEven` (isEven) vs
`shouldReportOddWhenNumberIsOdd` (isOdd) — not two different tests both called
`shouldReturnTrueWhenNumberIsOdd`.

This applies to new methods even in a class whose existing (human) methods use
another style: only an explicit repo instruction changes the rule.

**B2. `@DisplayName`:** the scenario description, in plain English. JUnit 5
only — JUnit 4 has no such annotation, so there the method name carries it and
nothing is added.

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

**B4. Assertions:** AssertJ when it is on the classpath, otherwise the
assertions of the JUnit version in use (`Assertions` in JUnit 5, `Assert` in
JUnit 4; for an exception there, `assertThrows` does not exist — use
`@Test(expected = ...)` only when no property has to be checked, otherwise
try/fail/catch and assert on the caught exception). An exception assertion checks the type AND the property that tells
it apart (status, code, message) — never a bare "throws". Not `assertNotNull`
alone, not `verify` alone.

**B5. Collaborators:** mock the classes that stand for a database or a network
boundary (repositories, gateways, clients) with Mockito; build real domain
objects, DTOs and value types. Wire Mockito the way the version wires it:
`@ExtendWith(MockitoExtension.class)` in JUnit 5,
`@RunWith(MockitoJUnitRunner.class)` in JUnit 4.

**B6. Setup:** the class under test, when every test builds it the same way,
is a field of the test class (`private final Calculator calculator = new
Calculator();`, or `@InjectMocks` with `@Mock` collaborators) — not a line in
each test's `// given`. Build it inside a test only when that test needs a
different construction. Likewise extract a private helper for construction repeated across tests
(`validRequest()`, `activeOffer()`) instead of repeating it.

**B7. Test class:** `<Target>Test` in the target's package under the test root,
unless a test class for the target already exists — then add to that one.
