# tc-agent — Model B (spec)

> Status: **wdrożony** (gałąź `model-b`; Model A zamrożony tagiem). Szczegóły decyzji D1–D27 i uzasadnienia: `docs/MODEL-B-PLAN.md`. Ten dokument opisuje architekturę; plan opisuje, jak do niej doszliśmy.

---

## 1. Po co ta zmiana (problem Modelu A)

W Modelu A plany, review i raporty były źródłem prawdy maszyny stanów — `tc_orchestrate.py state` liczył `next_action` wyłącznie z nich. Ale `.test-agent/` jest gitignorowany, więc źródło prawdy było **ulotne i per-maszyna**:

- **Zespół:** kolega bez `.test-agent/` planował od zera, a Phase 2.5 nie miała czego czytać.
- **Cross-machine / `git clean`:** stan znikał.
- **Fałszywy DONE (Case 1):** po zmianie kodu `state` dalej widział stare artefakty → `DONE`.
- **Ciężka machina:** wersjonowanie planów, dwie osie, delta-integrity, Phase 2.5, carry-forward, ledger — istniały głównie po to, by trzymać stan między przebiegami.

## 2. Zasada Modelu B

> **Prawda = zacommitowany KOD + TESTY + historia git.** Artefakty w `.test-agent/` nigdy nie są źródłem prawdy między przebiegami.

- Każdy przebieg ma **własny katalog** `.test-agent/runs/<slug>/<run-id>/` (gitignored). To medium przekazywania danych między rolami w obrębie przebiegu.
- **Nic nie jest kasowane.** Stare przebiegi zostają do wglądu (lokalnie i w workspace Jenkinsa), ale żaden skrypt nie czyta katalogu innego przebiegu.
- **Zacommitowany zestaw testów JEST bazą danych** — testy opisują się same (Javadoc, §3). Audyt „jak to ewoluowało” = historia git testów.

## 3. Metadane per test (schemat bazy)

Metadane są w **Javadoc nad METODĄ testu** — nigdy na klasie. Fakty maszynowe w liniach `tc-agent-<klucz>: <wartość>` (jedna na linię) — to zwykły tekst, nie tagi Javadoca `@…`, więc IDE i doclint niczego nie podkreślają. Proza w pierwszej linii.

```java
/**
 * AI-generated test. Characterizes current behaviour of OrderService (a freeze, not a spec).
 *
 * tc-agent: generated
 * tc-agent-mode: legacy
 * tc-agent-characterizes: OrderService@29aeef6a
 * tc-agent-note: business-hours guard off-by-one at 17:00 — reported as a defect, frozen as current behaviour
 */
@Test
@DisplayName("active customer can create an order")
void shouldCreateOrderWhenCustomerActive() { ... }
```

Zaślepka (scenariusz świadomie nieprzetestowany — deferred albo niemożliwy do zaimplementowania):

```java
/**
 * AI-generated placeholder. Scenario deliberately NOT tested — see tc-agent-deferred.
 *
 * tc-agent: generated
 * tc-agent-mode: legacy
 * tc-agent-characterizes: OrderService@29aeef6a
 * tc-agent-deferred: business-hours guard reads LocalDateTime.now() directly; needs an injected java.time.Clock
 */
@Test
@Disabled("AI deferred: needs a Clock seam")
void shouldRejectOrderWhenOutsideBusinessHours() {
}
```

| linia | znaczenie |
|---|---|
| `tc-agent: generated` | metodę napisał agent |
| `tc-agent-mode: legacy \| spec-driven` | tryb generacji |
| `tc-agent-interactive: true` | przebieg był z modyfikatorem interactive |
| `tc-agent-characterizes: <Class>@<sha>` | tylko legacy; `%h` ostatniego commita pliku targetu — punkt zamrożenia |
| `tc-agent-deferred: <powód>` | tylko w zaślepce `@Disabled("AI deferred: …")` z pustym ciałem |
| `tc-agent-note: <tekst>` | powtarzalny; zamrożony bug, odpowiedź człowieka — dotyczy TEJ metody |

Zasady:
- **Bez TC id w kodzie.** Scenariusz ↔ test łączy nazwa metody (`implementation_hints.test_method`).
- **Niezmiennik:** każdy scenariusz planu kończy w kodzie jako test albo zaślepka. Zaślepka to jedyny zapis, że luka jest znana i świadoma.
- **Porównanie sha po prefiksie** (w dowolną stronę, min. 7 znaków) — `%h` ma zmienną długość.
- **Spec-driven nie ma sha** — zamraża spec (ulotny), nie kod; brak auto-staleness jest zamierzony.
- Parser (`tc_javadoc.py`) nie zgaduje: linia zniekształcona, nieznany klucz, metadane na klasie, stary format `@aiGenerated`, zaślepka bez `@Disabled` → `metadata_defects` w derive-state.

## 4. derive-state (`tc_derive_state.py`)

Każdy przebieg zaczyna od wyprowadzenia stanu **z realnego świata**, warstwami — od najtańszej:

| tier | co | koszt |
|---|---|---|
| 0 | slug → plik, FQCN, moduł | ms |
| 1 | discovery klas testowych (ludzkie + AI, po nazwie lub użyciu targetu), parsowanie linii `tc-agent`, git: `%h`, dirty, wiek | ms |
| 2 | testy + coverage (JaCoCo) | build |
| 3 | mutacje (PIT) — tylko gdy tier 2 nie zdecydował | wolne |

**Stale** = test legacy z `tc-agent-characterizes: <Target>@sha`, gdzie sha ≠ bieżący `%h` pliku targetu, albo target jest dirty.
- stale i **zielony** → `reseal`: skrypt podmienia tylko linię `tc-agent-characterizes` (zachowanie się nie zmieniło),
- stale i **czerwony** → `recharacterize` → planer,
- stale **zaślepka** → `recharacterize` (ocenić na nowo).

`next_action`:

| wynik | kiedy |
|---|---|
| `PLAN` | `NO_TESTS`, `COVERAGE_GAP`, `MUTATION_GAP`, `UNTESTED_METHODS` (metoda bez ani jednej pokrytej linii — np. nowo dodana — nawet gdy bramka klasy przechodzi), `CHANGED_CODE_UNCOVERED` (linie zmienione od ostatniego zamrożenia, `git diff <sha>..HEAD`, których żaden test nie pokrywa), `STALE` |
| `DONE` | bramki spełnione na BIEŻĄCYM kodzie, nic stale nie jest czerwone |
| `RED` | czerwony test, który nie jest stale charakteryzacją (ludzki, świeży AI, spec-driven), albo błąd kompilacji |
| `BLOCKED` | `PLAN` w legacy, a target dirty (zawsze) lub młodszy niż `freshness_days` (chyba że interactive) |
| `ESCALATE` | target nie istnieje / niejednoznaczny, brak gita, check exit 2 |

> **DONE = bramki spełnione na bieżącym kodzie**, wyliczone świeżo — nie „mam zapisany ACCEPT”. Case 1 znika u źródła.

## 5. Przebieg (`tc_orchestrate.py`)

```
start  → run.json + derive-state.md          (jedyne miejsce na mode/interactive/spec/caps/--commit)
state  → PLAN | GENERATE | REVIEW | RESEAL | FINISH   (tylko z artefaktów TEGO przebiegu)
reseal → podmiana sha w zielonych testach stale
finish → run-report.md (+ commit przy --commit)
```

- Pętla PLAN → GENERATE → REVIEW → repair i capy (`impl_cap`, `plan_cap`) działają w obrębie przebiegu. REPAIR_PLAN = planowanie od nowa: planer widzi w kodzie testy z `tc-agent: generated`. Generator zawsze czyta najnowsze review przebiegu (bez carry-forward).
- Weryfikacja na wyjściu = **ACCEPT recenzenta** (nie ma drugiego derive-state).
- Wynik: `DONE` / `DONE_PARTIAL` (są zaślepki) / `BLOCKED` / `RED` / `ESCALATED`.
- **`--commit`**: tylko przy DONE / DONE_PARTIAL, tylko pliki testowe przebiegu, nigdy przy zabrudzonym indeksie, bez push. Na branchu chronionym (albo detached HEAD) tworzy `tc-agent/<slug>/<run-id>`. Lista chronionych: linia `tc-agent-protected-branches: …` w `AGENTS.md` repo docelowego; brak → tylko `master`.
- **Wiadomość commita:** tytuł (skrypt) + 2–5 zdań po angielsku od recenzenta (`commit_summary`) + blok faktów (skrypt: tryb, sha, liczby, bramki, sugestie, ścieżka raportu). Bez recenzenta — zdania z szablonu.

## 6. Co zniknęło z Modelu A

- wersjonowanie planów między przebiegami, dwie osie `change` / `implementation`, delta-integrity, `split_from`, `REMOVED`, `covered_by`,
- Phase 2.5, carry-forward findingów, `open_feedback_review`,
- ledger (`run-ledger.md`) i `clean`,
- znaczniki `// TC-nn`, `// AI GENERATED`, `// CHARACTERIZATION:`,
- freshness guard jako „STOP i czekaj na potwierdzenie” — teraz to deterministyczny `BLOCKED` w derive-state,
- zależność skryptów sprawdzających od planu (`load_plan` / `load_report`): target i klasy testowe są wyprowadzane ze sluga i systemu plików.

## 7. Co zostało

- **3 role + izolacja kontekstu** (niezależny recenzent), orchestrator jako dispatcher,
- **bramki coverage + mutacje** (egzekwowane, z profilu),
- **characterization** — przez `tc-agent-characterizes: Class@sha` w teście,
- **dyscyplina dowodów** (prime directive; implementacja = dowód w legacy),
- **context-pack** + wstrzykiwanie konwencji repo (§8),
- **skrypty** run_tests / coverage / mutation / validate / verify_refs / evidence_strength,
- **interactive** — odpowiedzi trafiają do `tc-agent-note` / zaślepek, pytania do `CONFIRM:` w raporcie.

## 8. Konwencje: agent kontra repo

Wszystko, czego agent potrzebuje do poprawnego działania, jedzie **z agentem** — `.github/agents/tc-agent/tc-test-conventions.md`:
- **§A integralność** (nienadpisywalna): metadane, zaślepki, charakteryzacja, dane z dowodów, determinizm, granice;
- **§B domyślne** (nadpisywalne przez repo): nazwy `shouldXxxWhenYyy`, `// given` / `// when` / `// then`, AssertJ, mocki repozytoriów, `<Target>Test`.

Instrukcje repo docelowego wstrzykuje context-pack (sekcja REPO CONVENTIONS): `.github/copilot-instructions.md`, `.github/instructions/*.instructions.md` filtrowane po `applyTo`, `AGENTS.md`, dodatkowe ścieżki z `instruction_paths` w profilu (także spoza `.github`). Pierwszeństwo regułą po regule: **§A > repo > §B**. Nadpisać §B może tylko jawna instrukcja — styl istniejących testów nie.

Propagacja instrukcji hosta do subagentów w Copilocie jest nieudokumentowana — pack jest kanałem pewnym.

## 9. Zespół / CI

Wszyscy dzielą kod + testy przez git; zero ukrytego stanu. Run kolegi albo Jenkinsa na świeżym workspace wyprowadza **identyczną prawdę**. W CI: `start … --commit` na detached HEAD tworzy branch `tc-agent/<slug>/<run-id>`; push i merge request są po stronie Jenkinsa.

## 10. Packaging pod Copilot (później, poza zakresem)

- `.github/agents/*.agent.md` = cienkie shimy (`model` + `tools` + „użyj skilla X”),
- `.github/skills/*/SKILL.md` = proza ról (progressive disclosure),
- wspólne skrypty w jednym miejscu, dystrybucja przez submodule / subtree,
- skill nie niesie modelu (`copilot-cli#1169`) → model zostaje na shimie.

## 11. Dev-testy

Bez Mavena i bez sieci: `tools/tc_test_javadoc.py`, `tc_test_derive_state.py`, `tc_test_run_state.py`, `tc_test_check_scripts.py` (prawdziwe skrypty przez fałszywy `mvn` z `tools/fake_mvn/`), `tc_test_build_context.py`, `tc_check_examples.py`. Z prawdziwym Mavenem: `tc_smoke_pipeline.py`.

## 12. Ryzyka / otwarte

- **Koszt per przebieg** — brak pamięci między przebiegami = testy + coverage (+ PIT) przy każdym starcie, gdy target ma testy. Warstwy ograniczają to do potrzebnego minimum.
- **Zaślepki a zmiany kodu** — każdy commit w targecie robi zaślepki legacy stale → pełen cykl planera, choć zwykle powód odroczenia (np. brak Clock) się nie zmienił. Do obserwacji; ewentualnie reseal zaślepek mechanicznie i ocena na nowo tylko przy luce w bramce.
- **DONE_PARTIAL poniżej bramki** — gdy luka jest większa niż bramka dopuszcza, ale w całości wyjaśniona zaślepkami, każdy przebieg kosztuje jedno wywołanie planera (COMPLETE).
- **Zaślepki utrzymywane ręcznie** — usunięcie zaślepki bez zmiany kodu = pipeline zapyta / odroczy ponownie (świadomy trade-off „zero plików”).
- **Sha per plik** — szum przy dużych klasach; łagodzi go reseal.
