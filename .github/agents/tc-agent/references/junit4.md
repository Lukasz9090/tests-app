# JUnit 4 module

The pack's TEST FRAMEWORK line says JUnit 4. Surefire does not fail a test of the
wrong version — it silently does not run it — so these replace the JUnit 5 parts
of `conventions.md`:

| conventions | on JUnit 4 |
|---|---|
| A2 placeholder | `@Ignore("AI deferred: …")` instead of `@Disabled`; no `@DisplayName` |
| A7 parameterized test | not allowed: `@RunWith(Parameterized)` takes over the whole class — one plain method per scenario |
| B2 `@DisplayName` | does not exist; the method name carries the description |
| B4 assertions without AssertJ | `org.junit.Assert`; for an exception there is no `assertThrows`: `@Test(expected = ...)` only when no property has to be checked, otherwise try / `fail()` / catch and assert on the caught exception |
| B5 Mockito wiring | `@RunWith(MockitoJUnitRunner.class)` |

`import org.junit.Test` (not `org.junit.jupiter.api.Test`), public test methods
and a public test class.

A planner on JUnit 4 never plans a parameterized scenario. A reviewer on JUnit 4
does not report a missing `@DisplayName` or a set of sibling non-parameterized
tests.
