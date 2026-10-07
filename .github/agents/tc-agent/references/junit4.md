# JUnit 4 module

The pack's TEST FRAMEWORK line says JUnit 4. Surefire does not fail a test of the
wrong version — it silently does not run it — so these replace the JUnit 5 parts
of `conventions.md`:

| conventions | on JUnit 4 |
|---|---|
| A2 placeholder | `@Ignore("AI deferred: …")` instead of `@Disabled`; no `@DisplayName` |
| A7 parameterized test | not allowed: `@RunWith(Parameterized)` takes over the whole class — one plain method per scenario |
| B2 `@DisplayName` | does not exist; the method name carries the description |
| B3 / B4 exceptions | AssertJ `catchThrowable` works as on JUnit 5. Without AssertJ (`org.junit.Assert`, no `assertThrows`): in `// when` catch it into a variable (`ApiException thrown = null; try { service.create(request); } catch (ApiException e) { thrown = e; }`), in `// then` assert it is not null and check its property. Never `@Test(expected = ...)`: it leaves no `// then` |
| B5 Mockito wiring | `@RunWith(MockitoJUnitRunner.class)` |

`import org.junit.Test` (not `org.junit.jupiter.api.Test`), public test methods
and a public test class.

A planner on JUnit 4 never plans a parameterized scenario. A reviewer on JUnit 4
does not report a missing `@DisplayName` or a set of sibling non-parameterized
tests.
