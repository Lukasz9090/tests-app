# Test conventions (tc-agent)

Repo-agnostic conventions for every test this pipeline writes or reviews. They
travel with the agent, so a repository needs no file of its own for the agent to
work correctly.

    §A pipeline integrity  >  repo instructions (REPO CONVENTIONS in the pack)  >  §B defaults

A repo instruction may replace any §B rule; it can never relax an §A rule.

## §A — Pipeline integrity (not overridable)

**A0. The test framework is the repo's.** The pack's TEST FRAMEWORK line (from
`derive-state.md` `repo.junit`, read from the module's existing tests first,
the poms only as a fallback) decides the annotations you write. Never add a
dependency to get another framework. `junit_mixed: true` means the module holds
both: match the class you extend. Unknown framework: follow the existing test
class; with none, write JUnit 5 and say so in your artifact's `notes`. The rules
below are written for JUnit 5; on JUnit 4 `junit4.md` replaces the
framework-specific parts.

**A1. Metadata.** Every test method you write carries a Javadoc: one prose line,
a blank line, then one `tc-agent-<key>: <value>` line per fact — plain text,
lowercase key, a colon, a space; never Javadoc `@tags`. On METHODS only, never
on the test class.

```java
/**
 * AI-generated test. Characterizes current behavior of OrderService (a freeze, not a spec).
 *
 * tc-agent-mode: characterization, interactive: false
 * tc-agent-characterizes: OrderService@29aeef6a
 */
```

| line | when |
|---|---|
| `tc-agent-mode: <mode>, interactive: <true\|false>` | always; both values from `run.json`, `interactive` written also when false |
| `tc-agent-characterizes: <Class>@<sha>` | characterization mode only; `<sha>` = the plan's `context.target_sha` |
| `tc-agent-spec: <spec file>#<requirement>` | spec-driven mode only; the requirement id or heading the test comes from |
| `tc-agent-deferred: <reason>` | placeholders only (A2) |
| `tc-agent-note: <text>` | optional, repeatable: a fact about THIS test (a frozen known bug, a human's answer) |

First prose line: the mode file gives it for tests; for placeholders it is
`AI-generated placeholder. Scenario deliberately NOT tested — see tc-agent-deferred.`
Any other `tc-agent...:` key is a defect. Never add these lines to a method you
did not write, never remove them from one you repair, and when you rewrite a
method (`replaces`) replace its whole Javadoc.

**A2. Placeholders.** A scenario that is deferred, or cannot be implemented
soundly, becomes an empty, disabled method:

```java
/**
 * AI-generated placeholder. Scenario deliberately NOT tested — see tc-agent-deferred.
 *
 * tc-agent-mode: characterization, interactive: false
 * tc-agent-characterizes: AppointmentService@29aeef6a
 * tc-agent-deferred: business-hours guard reads LocalDateTime.now() directly; needs an injected java.time.Clock
 */
@Test
@Disabled("AI deferred: needs a Clock seam")
@DisplayName("appointment outside business hours is rejected")
void shouldRejectAppointmentWhenOutsideBusinessHours() {
}
```

- the body is empty; the `@Disabled` text starts with `AI deferred:`;
- `tc-agent-deferred` carries the full reason; for a compile error, the compiler message;
- a placeholder is ONLY for behavior that cannot be tested: no code seam (A5), a
  value whose meaning nothing backs (A4), a compile error that could not be fixed.
  Never for a name clash, a relational value or object shape (A4), or a type
  missing from the pack (`contracts.md` §5).

**A3. Mode semantics** — what a test asserts (current behavior or the spec) is
defined by the run's mode file.

**A4. Data.** An LLM is never the source of truth about business data: every
value whose MEANING matters (an id, a code, a status the code switches on, a
threshold, an amount) comes from evidence. Look for it in this order and take
the first that answers:

1. TEST DATA in the pack — files a human named for this repository or run;
2. `known_test_data` — what a human answered earlier in this run;
3. DATA EXAMPLES and the existing tests in the pack — a value a test anywhere in
   the repository already uses shows the shape; cite that line (`existing_test`);
4. builders, fixtures, seeders, enums and validation constraints (`@Pattern`,
   `@Size`) in the pack;
5. a human — only in an `interactive` run (`modes/interactive.md`);
6. nothing found: the scenario is deferred with a question.

A literal in the production code shows what a guard compares, not what a real
value looks like. A value from these sources comes with a SHAPE (`customer id:
9 digits, e.g. 123456789`): use the shape, not one literal — every field of that
kind and every distinct entity gets its OWN value of that shape, never one id
for two parties; the same value only when it means the same entity.
Identifiers with a checksum (PESEL, NIP, REGON, IBAN, account numbers) are
copied from an example, never derived from the shape.

Two things are NOT business data and never make a scenario a placeholder:
- **Relational values** — a value whose only role is to equal (or not equal)
  another value the test also controls: a key compared with the key of an entry
  a mock returns, an id passed in and echoed back; the comparison line is the
  evidence. When sources 1–4 show the shape of that field, use the shape — a
  relational customer id still looks like a customer id. Only a field with no
  known shape gets a neutral literal named so nobody reads it as real data
  (`"KEY-1"` / `"OTHER-KEY"`).
- **Object shapes** — a DTO or domain object built with its own constructor,
  builder or setters; the class declaration is the evidence. Fill only the
  fields the code under test reads.

**A5. Determinism.** No test may depend on the wall clock, the date, random
values, execution order or sleeps. When production code reads the clock
directly, build times RELATIVE to now and satisfy every guard that precedes the
one under test. When a branch cannot be made deterministic without a code seam,
write a placeholder (A2) and a suggestion ("inject java.time.Clock and use
LocalDateTime.now(clock)"). A flaky test is the worst possible output.

**A6. Boundaries.** Never modify production code. Never mock the class under
test. Never delete a test — recommend it instead.

**A7. One scenario, one method.** A parameterized test may cover sibling
scenarios of the same shape; list each covered scenario's description in a
`tc-agent-note`.

## §B — Defaults (a repo instruction may replace any of these)

**B1. Method names:** lowerCamelCase `should<Outcome>When<Condition>`, no
underscores, no `test` prefix; `should<Outcome>` when there is no meaningful
condition. The outcome names the operation, so tests of sibling methods never
share a name: `shouldReportEvenWhenNumberIsEven` (isEven) vs
`shouldReportOddWhenNumberIsOdd` (isOdd). Applies to new methods also in a class
whose human methods use another style — only an explicit repo instruction
changes the rule.

**B2. `@DisplayName`:** the scenario description, in plain English.

**B3. Structure:** `// given`, `// when`, `// then`, separated by a blank line;
`// when & then` when act and assert are one statement (an exception assertion).
An empty section is left out. Placeholders have no sections.

```java
// when & then
assertThatThrownBy(() -> service.create(request))
    .isInstanceOf(ApiException.class)
    .extracting("status").isEqualTo(HttpStatus.NOT_FOUND);
```

**B4. Assertions:** AssertJ when it is on the classpath, otherwise the JUnit
assertions. An exception assertion checks the type AND the property that tells
it apart (status, code, message) — never a bare "throws". Not `assertNotNull`
alone, not `verify` alone.

**B5. Collaborators:** mock the classes that stand for a database or network
boundary (repositories, gateways, clients) with Mockito
(`@ExtendWith(MockitoExtension.class)`); build real domain objects, DTOs and
value types.

**B6. Setup:** the class under test, when every test builds it the same way, is a
field (`private final Calculator calculator = new Calculator();`, or `@InjectMocks`
with `@Mock` collaborators). Extract a private helper for construction repeated
across tests (`validRequest()`, `activeOffer()`).

**B7. Test class:** `<Target>Test` in the target's package under the test root,
unless a test class for the target already exists — then add to that one.
