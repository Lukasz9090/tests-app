# tc-agent — Model B: plan wdrożenia (stan docelowy)

> **Status:** plan zweryfikowany 2026-09-21 i **wdrożony** (etapy 1–8). Etap 9 (end-to-end E1–E17 z prawdziwym Mavenem i Copilotem) — po Twojej stronie. Odchylenia od planu: patrz §14.
> **Baza:** `docs/MODEL-B-SPEC.md` oraz decyzje z sesji planistycznej. Jeśli ten plik mówi coś innego niż spec, obowiązuje ten plik, a spec zaktualizuję w etapie 1.
> **Punkt powrotu:** tag Modelu A już istnieje. Pracujemy na gałęzi `model-b`, bo pipeline między etapami 2 a 7 nie będzie działał.

Wszystkie pozycje w §1 są zaakceptowanymi decyzjami.

---

## 1. Decyzje — podsumowanie

| # | obszar | ustalenie | status |
|---|---|---|---|
| D1 | Źródło prawdy między przebiegami | kod, testy, git, coverage i PIT, liczone od zera przez `derive-state`. Żaden artefakt nie jest czytany jako stan. | DECYZJA |
| D2 | Stan w obrębie przebiegu | Kursor w `.test-agent/runs/<slug>/<run-id>/`. Pętla PLAN → GENERATE → REVIEW i capy działają jak dziś, ale tylko w obrębie jednego przebiegu. | DECYZJA |
| D3 | Koszt derive-state | Liczony warstwami: tier 1 (git i Javadoc) → tier 2 (testy i coverage) → tier 3 (PIT). Kolejna warstwa rusza tylko wtedy, gdy poprzednia nie podjęła decyzji. | DECYZJA |
| D4 | Freshness guard | Tryb legacy bez interactive i target dirty albo z commitem młodszym niż N dni → deterministyczny `BLOCKED` z raportem. Z interactive planer może zapytać i kontynuować. Spec-driven nie ma guarda. | DECYZJA |
| D4a | Dirty a interactive | Target dirty w legacy → `BLOCKED` zawsze, także z interactive. Niezacommitowany kod nie ma sha, który dałoby się wpisać do `@characterizes`. | DECYZJA |
| D5 | Traceability | TC id istnieje tylko w artefaktach przebiegu. Scenariusz łączy się z kodem przez nazwę metody (`implementation_hints.test_method`). W kodzie nie ma `// TC-nn`. | DECYZJA |
| D6 | Tagi | Wyłącznie na metodach. Klasa testowa nie ma żadnych tagów. | DECYZJA |
| D7 | `@note` | Na metodzie testu, którego dotyczy. | DECYZJA |
| D8 | Świadomie nieprzetestowane (deferred / unimplementable) | Metoda-zaślepka z `@Disabled` i Javadociem `@deferred`, w legacy dodatkowo `@characterizes`. | DECYZJA |
| D9 | DONE poniżej bramki | `DONE_PARTIAL`: planer potwierdza, że całą pozostałą lukę wyjaśniają zaślepki. | DECYZJA |
| D10 | Porównanie sha | Sha per plik z `%h`. Zgodność, gdy jeden ciąg jest prefiksem drugiego (min. 7 znaków). | DECYZJA |
| D11 | Testy do pomiaru | Klasy testowe odwołujące się do targetu, ludzkie i AI razem. | DECYZJA |
| D12 | Czyszczenie `.test-agent/` | Brak. Każdy przebieg ma nowy katalog, stare zostają do wglądu (gitignored). | DECYZJA |
| D13 | Weryfikacja na wyjściu | ACCEPT recenzenta. Nie ma drugiego derive-state na końcu. | DECYZJA |
| D14 | Packaging (§11 speca) | Poza zakresem. | DECYZJA |
| D15 | Reseal | Test legacy, który jest stale, ale nadal zielony, dostaje mechaniczną podmianę sha (skrypt). Do planera trafiają tylko testy stale i czerwone. | DECYZJA (§4.4) |
| D16 | Mode i interactive | Podawane raz, do `start`, i zapisywane w `run.json`. Role czytają je z manifestu, a orchestrator przestaje je przekazywać. | DECYZJA (§5.2) |
| D17 | Wynik zapisu | Domyślnie pipeline nie commituje. Opcjonalna flaga `--commit` w `start`: commit tylko przy DONE / DONE_PARTIAL, tylko pliki testowe zmienione w tym przebiegu, bez push. Na branchu chronionym agent tworzy nowy branch `tc-agent/<slug>/<run-id>`. | DECYZJA (§5.6) |
| D18 | Konwencje testów | Należą do **agenta**, a nie do repo. Nowy plik `tc-test-conventions.md` w pakiecie agenta; czytają go wszystkie role, które piszą lub oceniają testy. `AGENTS.md` repo przestaje nieść reguły agenta. | DECYZJA (§10) |
| D19 | Warstwy | Integralność pipeline'u (nienadpisywalna) > instrukcje repo docelowego > domyślne konwencje agenta. | DECYZJA (spec §10) |
| D20 | Nazwy metod | Domyślnie `shouldXxxWhenYyy` (lowerCamelCase, bez podkreśleń). Nadpisywalne instrukcją repo. | DECYZJA |
| D21 | Struktura testu | Domyślnie sekcje `// given`, `// when`, `// then` (`// when & then` dla asercji wyjątku). Nadpisywalne instrukcją repo. | DECYZJA |
| D22 | Co liczy się jako „instrukcja repo” | Tylko jawne pliki instrukcji. Styl istniejących testów **nie** zmienia domyślnych reguł (w jednej klasie mogą być dwa style). | DECYZJA (§10.4) |
| D23 | Nieudana naprawa kompilacji | Generator, który nie umie naprawić błędu kompilacji, zostawia zaślepkę `@Disabled` z komunikatem kompilatora w `@deferred`. | DECYZJA (§6.3) |
| D24 | Nowa klasa testowa | `<Target>Test`, gdy dla targetu żadna klasa jeszcze nie istnieje. | DECYZJA (§10.5 B7) |
| D25 | `AGENTS.md` w tests-app | Zostaje tylko odnośnik dla ludzi, bez reguł dotyczących pisania testów. | DECYZJA (§10.6) |
| D26 | Branche chronione | Lista w `AGENTS.md` repo docelowego, w jednej linii `tc-agent-protected-branches:`. Brak linii → chroniony jest tylko `master`. Agent nigdy nie commituje na branch chroniony. | DECYZJA (§5.6) |
| D27 | Wiadomość commita | Tytuł (skrypt) + podsumowanie prozą 2–5 zdań (recenzent, pole `commit_summary`) + blok faktów (skrypt). Bez recenzenta: zdania z szablonu. | DECYZJA (§5.6) |

---

## 2. Przebieg z lotu ptaka

```
                     ┌─────────────────────────────────────────────┐
  tc_orchestrate.py  │  start <slug> --mode --interactive --spec   │
                     │   1. nowy katalog runs/<slug>/<run-id>/      │
                     │   2. run.json (manifest)                     │
                     │   3. derive-state  ──► derive-state.md       │
                     └───────────────┬─────────────────────────────┘
                                     │ next_action
        ┌───────────────┬────────────┼──────────────┬───────────────┐
        ▼               ▼            ▼              ▼               ▼
      DONE            RED        BLOCKED        ESCALATE          PLAN
   (nic do zrobienia) (czerwone  (freshness     (tooling /     (brak testów /
        │           testy ludzi) guard)         target)        luka / stale)
        │               │            │              │               │
        │               │            │              │      ┌────────▼─────────┐
        │               │            │              │      │ pętla w przebiegu│
        │               │            │              │      │ RESEAL? → PLAN → │
        │               │            │              │      │ GENERATE → REVIEW│
        │               │            │              │      │ (capy impl/plan) │
        │               │            │              │      └────────┬─────────┘
        ▼               ▼            ▼              ▼               ▼
                     ┌─────────────────────────────────────────────┐
                     │  finish  ──►  run-report.md + podsumowanie   │
                     │  outcome: DONE | DONE_PARTIAL | BLOCKED |    │
                     │           RED | ESCALATED                    │
                     └─────────────────────────────────────────────┘
```

Najważniejsza właściwość: **derive-state patrzy tylko na świat, a pętla tylko na swój katalog**. Dwa przebiegi nigdy nie dzielą stanu. Kolega, który sklonuje repo, albo Jenkins na świeżym agencie dostaną ten sam wynik `start`.

---

## 3. Metadane w kodzie (schemat „bazy danych”)

### 3.1 Tagi (lista zamknięta)

Wszystkie tagi są **wyłącznie na metodach** (D6).

| tag | wymagany | znaczenie |
|---|---|---|
| `@aiGenerated` | zawsze | metodę napisał agent |
| `@mode legacy` / `@mode spec-driven` | zawsze | tryb generacji |
| `@interactive` | gdy przebieg miał interactive | modyfikator był włączony |
| `@characterizes <Class>@<sha>` | tylko legacy (także w zaślepce) | punkt zamrożenia do wykrywania driftu |
| `@deferred <powód>` | tylko w zaślepce | scenariusz świadomie nieprzetestowany i powód |
| `@note <tekst>` | opcjonalny, może się powtarzać | zamrożony znany bug, odpowiedź człowieka z interactive, uwaga |

Pierwsza linia Javadoca to proza dla człowieka. Tagi są maszynowe: jeden tag na linię, wartość ciągnie się do końca linii.

### 3.2 Test legacy

```java
/**
 * AI-generated test. Characterizes current behaviour of AppointmentService (a freeze, not a spec).
 *
 * @aiGenerated
 * @mode legacy
 * @characterizes AppointmentService@29aeef6a
 */
@Test
@DisplayName("active customer can create an appointment")
void shouldSaveScheduledAppointmentWhenRequestIsValid() {
    // given
    CreateAppointmentRequest request = validRequest();
    when(offerRepository.findById(OFFER_ID)).thenReturn(Optional.of(activeOffer()));

    // when
    AppointmentResponse response = service.create(request);

    // then
    assertThat(response.status()).isEqualTo(AppointmentStatus.SCHEDULED);
}
```

Nazwa metody i sekcje `given/when/then` to domyślne konwencje agenta (§10), a nie część metadanych — repo może je nadpisać. Javadoc z tagami jest nienadpisywalny.

### 3.3 Test legacy z interactive i notatką

```java
/**
 * AI-generated test. Characterizes current behaviour of AppointmentService (a freeze, not a spec).
 *
 * @aiGenerated
 * @mode legacy
 * @interactive
 * @characterizes AppointmentService@29aeef6a
 * @note business-hours guard rejects 17:00 exactly — human reported it as a defect; frozen as current behaviour, not fixed
 */
```

Odpowiedzi człowieka z interactive lądują tak (to zastępuje dzisiejsze `human_decision`, które żyło tylko w planie):

| odpowiedź | co powstaje w kodzie |
|---|---|
| „tak, to poprawne” | test + `@note human-confirmed: <co>` |
| „to bug” | test zamrażający obecne zachowanie + `@note reported as defect: <co>` |
| „nie wiem / pomiń” | zaślepka `@deferred` z pytaniem w powodzie |

### 3.4 Test spec-driven

```java
/**
 * AI-generated test. Based on a specification provided at generation time (not stored in the repo).
 *
 * @aiGenerated
 * @mode spec-driven
 */
```

Test spec-driven nie ma sha, więc nigdy nie staje się stale (świadomy trade-off ze speca, §13).

### 3.5 Zaślepka (D8)

```java
/**
 * AI-generated placeholder. Scenario deliberately NOT tested — see @deferred.
 *
 * @aiGenerated
 * @mode legacy
 * @characterizes AppointmentService@29aeef6a
 * @deferred business-hours guard reads LocalDateTime.now() directly; needs an injected java.time.Clock
 */
@Test
@Disabled("AI deferred: needs a Clock seam")
@DisplayName("appointment outside business hours is rejected")
void shouldRejectAppointmentWhenOutsideBusinessHours() {
}
```

Reguły:
- ciało jest puste, adnotacja `@Disabled` jest obowiązkowa, a jej tekst zaczyna się od `AI deferred:`;
- zaślepka powstaje w dwóch przypadkach: scenariusz trafił do `deferred` w planie (słabe dowody) albo generator nie mógł go zaimplementować (BLOCKED, np. brak seamu Clock);
- **niezmiennik:** każdy scenariusz planu kończy w kodzie jako test albo jako zaślepka. Recenzent to sprawdza;
- zaślepka legacy ma `@characterizes`, więc gdy kod się zmieni, zostaje oceniona na nowo jak każdy test legacy (może da się ją już zaimplementować, np. po dodaniu Clock);
- żeby „odblokować” scenariusz, człowiek usuwa zaślepkę albo zmienia kod. Następny przebieg sam wykryje lukę.

### 3.6 Co znika z kodu

- `// TC-nn`,
- `// AI GENERATED`,
- `// CHARACTERIZATION: freezes ...`,
- jakiekolwiek tagi na klasie.

Istniejące testy z konwencją Modelu A nie są migrowane automatycznie. Parser rozpoznaje je jako **testy bez metadanych**, czyli traktuje jak ludzkie. Jeśli masz takie w repo i chcesz je przenieść, zrobimy jednorazowy skrypt migracyjny (patrz §12, R6).

### 3.7 Parsowanie

- Nowy moduł `tc_javadoc.py` zawiera prosty skaner znakowy (nie regex na całości), bo adnotacje takie jak `@DisplayName("a (b)")` mają nawiasy w stringach.
- Dla każdej metody z `@Test`, `@ParameterizedTest` albo `@RepeatedTest` zwraca: klasę, nazwę metody, linię, `disabled`, tagi `{aiGenerated, mode, interactive, characterizes: {class, sha}, deferred, notes[]}`.
- Tag nieznany albo zniekształcony (np. `@characterizes` bez `@`) nie jest ignorowany po cichu, tylko trafia do `metadata_defects` w derive-state.
- Doclint: przed etapem 7 sprawdzę, czy pom ma javadoc plugin z strict doclint. Jeśli tak, zarejestrujemy tagi.

---

## 4. derive-state (`tc_derive_state.py`)

### 4.1 Wejście

```
python $C/tc_derive_state.py <slug> --repo . --run-dir <path> --mode legacy|spec-driven [--interactive]
```

Zwykle nie wołamy go ręcznie, tylko przez `tc_orchestrate.py start`. Skrypt **niczego nie zmienia w repo**: pisze wyłącznie do `<run-dir>`.

### 4.2 Warstwy

**Tier 0 — target.** Slug → plik, FQCN, moduł i metoda, wyznaczane z systemu plików (logika z `tc_build_context.py` przeniesiona do `tc_common.resolve_target`).
- `TARGET_NOT_FOUND`, `TARGET_AMBIGUOUS`, brak `pom.xml` → **ESCALATE**.

**Tier 1 — git i Javadoc (milisekundy, bez builda).**
1. Discovery klas testowych (D11): pliki w test roots, których nazwa zawiera nazwę targetu albo których treść używa jej jako całego słowa.
2. Parsowanie metod i tagów (§3.7).
3. Git dla pliku targetu: `current_sha` = `git log -1 --format=%h -- <plik>`, `dirty` = niepusty `git status --porcelain -- <plik>`, `age_days` z `%ct`.
4. Wstępna klasyfikacja testów legacy, które charakteryzują ten target (`@characterizes <TargetClass>@...`):
   - `sha_match` = prefiks w dowolną stronę, min. 7 znaków (D10),
   - `stale_candidate` = `!sha_match` albo `dirty`.
5. **Skrót:** brak jakichkolwiek klas testowych → `PLAN` z powodem `NO_TESTS`, bez tier 2 i 3.

**Tier 2 — testy i coverage (build).**
1. `tc_run_tests.py` na odkrytych klasach, `--repeat 1`.
2. Tooling exit 2 → **ESCALATE**. `COMPILE_ERROR` → **RED**.
3. Klasyfikacja wyników:

   | test | wynik | klasyfikacja |
   |---|---|---|
   | legacy AI, stale | zielony | `reseal` (D15) |
   | legacy AI, stale | czerwony | `recharacterize` → do planera |
   | legacy AI, aktualny | czerwony | `red` (coś się rozjechało, sha zgodny — np. zależność) |
   | spec-driven AI | czerwony | `red` (kod albo spec — decyduje człowiek) |
   | ludzki | czerwony | `red` |
   | dowolny | zielony | ok |

4. Jakikolwiek `red` → **RED** (stop, raport). Pipeline nie naprawia cudzych czerwonych testów.
5. `tc_coverage.py` → poniżej bramki albo niepuste `recharacterize` → **PLAN** z powodem `COVERAGE_GAP` i/lub `STALE`, z listą niepokrytych linii. Tier 3 nie rusza.

**Tier 3 — mutacje.**
1. `tc_mutation.py` na odkrytych klasach.
2. Wynik poniżej bramki → **PLAN** z powodem `MUTATION_GAP` i listą przeżywających mutantów.
3. W przeciwnym razie → **DONE**.

**Freshness guard (D4)** jest liczony na końcu i tylko wtedy, gdy wynik to `PLAN`. Wtedy bowiem naprawdę coś byśmy zamrażali. Przy `DONE`, `RED` i samym resealu guard nie blokuje.

```
if next_action == PLAN and mode == legacy:
    if dirty:                                   -> BLOCKED (reason: TARGET_DIRTY)       # D4a
    elif age_days < freshness_days and not interactive:
                                                -> BLOCKED (reason: TARGET_TOO_FRESH)
```

`freshness_days` pochodzi z `tc-project-profile.md` (domyślnie 7).

### 4.3 Wyjście — `<run-dir>/derive-state.md`

Kontener jak wszystkie artefakty: tytuł, krótkie podsumowanie, jeden fence json.

```json
{
  "schema_version": 1,
  "target": { "class": "AppointmentService", "fqcn": "com.testsapp.service.AppointmentService",
              "file": "src/main/java/com/testsapp/service/AppointmentService.java", "module": null },
  "git": { "current_sha": "4b1c2aa9", "dirty": false, "age_days": 12 },
  "tests": {
    "classes": ["com.testsapp.service.AppointmentServiceTests"],
    "ai":     [ { "method": "AppointmentServiceTests#shouldSaveScheduledAppointmentWhenRequestIsValid", "mode": "legacy",
                  "characterizes": "AppointmentService@29aeef6a", "status": "reseal" } ],
    "placeholders": [ { "method": "AppointmentServiceTests#shouldRejectAppointmentWhenOutsideBusinessHours",
                        "deferred": "business-hours guard reads LocalDateTime.now() ..." } ],
    "human_count": 4,
    "metadata_defects": []
  },
  "reseal": ["AppointmentServiceTests#shouldSaveScheduledAppointmentWhenRequestIsValid"],
  "recharacterize": [],
  "red": [],
  "coverage": { "status": "FAILED", "branch_ratio": 0.71, "gate": 0.80, "uncovered": [ { "line": 147, "missed_branches": 1 } ] },
  "mutation": { "status": "NOT_RUN" },
  "tiers_run": [0, 1, 2],
  "next_action": "PLAN",
  "reasons": ["COVERAGE_GAP"]
}
```

`next_action` przyjmuje jedną z wartości: `PLAN`, `DONE`, `RED`, `BLOCKED`, `ESCALATE`.

Ten plik jest **wejściem planera** i zastępuje dzisiejszą Phase 2.5. Planer nie grepuje w poszukiwaniu „własnych” testów, bo ma gotową listę: testy AI, zaślepki, ludzkie, stale, niepokryte linie i mutanty.

### 4.4 Reseal (D15)

**Problem.** Sha jest per plik (D10). Commit w dowolnej metodzie klasy unieważnia więc wszystkie jej testy legacy. Dla targetu `Class.method` robi się z tego pętla: przebieg na metodzie A nigdy nie „wyczyści” staleness testów metody B.

**Rozwiązanie.** Jeśli test stale jest nadal zielony na nowym kodzie, to zachowanie, które zamrażał, się nie zmieniło. Nie trzeba go wtedy re-charakteryzować, wystarczy przesunąć punkt zamrożenia:

```
python $C/tc_orchestrate.py reseal <slug> --run <id> --repo .
```

- podmienia wyłącznie linię `@characterizes <Class>@<old>` → `@<current_sha>` w metodach z listy `reseal`,
- niczego więcej nie dotyka i nie działa, gdy target jest dirty (nie ma sha),
- zmiana jest widoczna w diffie („29aeef6a → 4b1c2aa9”), więc człowiek widzi ją przy commicie.

Luki, które commit mógł otworzyć (nowa gałąź), łapie coverage i PIT, a nie reseal. Do planera trafiają więc tylko testy **stale i czerwone**, czyli realne zmiany zachowania.


---

## 5. Przebieg (run)

### 5.1 Katalog przebiegu

```
.test-agent/runs/<slug>/<run-id>/          # run-id = YYYYMMDD-HHMMSS
  run.json                  # manifest (D16)
  derive-state.md           # §4.3
  context-pack.md           # tc_build_context.py
  plan-v1.md [plan-v2.md]   # numeracja tylko na potrzeby plan_cap
  generation-report-v1.md [ -v1-r2.md ... ]
  review-v1-r1.md [ ... ]
  checks/                   # tests-*.md, coverage-*.md, mutation-*.md, jacoco.exec, maven-*.log
  run-report.md             # finish
```

Nic nie jest kasowane (D12). Żaden skrypt nie czyta katalogu **innego** przebiegu. `latest` to alias na najnowszy katalog danego sluga, przydatny przy wznawianiu.

### 5.2 `run.json` (D16)

```json
{
  "schema_version": 1,
  "slug": "AppointmentService",
  "run_id": "20260921-101500",
  "mode": "legacy",
  "interactive": false,
  "spec": null,
  "caps": { "impl_cap": 3, "plan_cap": 2 },
  "commit": false,
  "started": "2026-09-21T10:15:00+02:00",
  "resealed": false
}
```

Dziś orchestrator musi pamiętać, żeby `mode` podać planerowi, ale nigdy skryptom. To było źródło błędów, stąd długie ostrzeżenia w prompcie. W Modelu B mode, interactive i spec podaje się **raz**, do `start`, a każda rola czyta je z manifestu.

### 5.3 Komendy `tc_orchestrate.py`

| komenda | co robi |
|---|---|
| `start <slug> --repo . --mode M [--interactive] [--spec P] [--impl-cap 3] [--plan-cap 2] [--commit]` | tworzy katalog, `run.json`, wywołuje derive-state, wypisuje `run_id` i stan |
| `state <slug> --run <id\|latest> --repo .` | liczy `next_action` w przebiegu z artefaktów w katalogu przebiegu |
| `reseal <slug> --run <id> --repo .` | §4.4 |
| `finish <slug> --run <id> --repo .` | składa `run-report.md`, wypisuje outcome i podsumowanie; przy `commit: true` wykonuje commit wg §5.6 |

Znikają: `ledger` i `clean`.

### 5.4 Maszyna stanów w przebiegu (`state`)

Pierwsza pasująca reguła wygrywa:

| # | warunek | `next_action` |
|---|---|---|
| 1 | derive-state = `DONE`, `RED`, `BLOCKED` albo `ESCALATE`, a reseal nie jest potrzebny | `FINISH` |
| 2 | lista `reseal` niepusta i `run.json.resealed == false` | `RESEAL` |
| 3 | derive-state = `DONE` (po resealu) | `FINISH` |
| 4 | brak planu | `PLAN` (v1) |
| 5 | plan nieparsowalny | `FINISH` (ESCALATED) |
| 6 | status planu `BLOCKED` / `NEEDS_CLARIFICATION` / `UNSUPPORTED_REPOSITORY` | `FINISH` (BLOCKED / ESCALATED) |
| 7 | status planu `COMPLETE` | `FINISH` (DONE_PARTIAL, gdy są zaślepki, w przeciwnym razie DONE) |
| 8 | `READY` / `READY_PARTIAL` bez generacji | `GENERATE` (r1) |
| 9 | generacja bez review | `REVIEW` |
| 10 | review `ACCEPT` | `FINISH` (DONE, a przy zaślepkach DONE_PARTIAL) |
| 11 | review `ACCEPT_PARTIAL` | `FINISH` (DONE_PARTIAL) |
| 12 | review `NEEDS_TRIAGE` / `BLOCKED` | `FINISH` (ESCALATED) |
| 13 | review `REPAIR_IMPLEMENTATION`, runda < impl_cap | `GENERATE` (r+1) |
| 14 | review `REPAIR_PLAN`, wersja < plan_cap | `PLAN` (v+1) |
| 15 | cap osiągnięty | `FINISH` (ESCALATED, z powodem) |

Uproszczenia względem Modelu A:
- **carry-forward znika.** Generator zawsze czyta **najnowsze review w tym przebiegu**, niezależnie od wersji planu. Finding żyje, dopóki późniejsze review go nie zamknie.
- **REPAIR_PLAN = planowanie od zera.** Planer v2 widzi w kodzie testy napisane w r1 (z `@aiGenerated`) i planuje tylko to, czego brakuje. Nie ma delta-integrity, osi `change`/`implementation` ani `split_from`.
- `dispatch` w wyjściu `state` zawiera tylko `agent`, `run_dir` oraz ścieżki plik do zapisania / przeczytania.

### 5.5 `run-report.md` (`finish`)

Skrypt (nie LLM) składa z artefaktów przebiegu:

1. **Outcome i powód** — `DONE` / `DONE_PARTIAL` / `BLOCKED` / `RED` / `ESCALATED`.
2. **Czerwone testy na początku**, jeśli ostatni check testów jest czerwony: nazwa, `location`, faza, komunikat. Build jest zepsuty, dopóki ktoś nie zareaguje.
3. Co zmieniono w working tree: testy dodane, testy zmienione, zaślepki, reseal.
4. `unimplementable` i `suggestions` (seamy w kodzie, np. Clock) — rekomendacje, nigdy nie są stosowane automatycznie.
5. Pytania `CONFIRM:` z planu (dla przebiegów bez człowieka).
6. Liczby bramek z ostatniego review albo z derive-state.
7. **Co dalej dla człowieka**, np. „zacommituj zmiany w `AppointmentServiceTests.java`”, „commit targetu jest młodszy niż 7 dni — uruchom z `--interactive` albo w trybie spec-driven”.

Orchestrator wyświetla ten raport i nie dopisuje od siebie żadnej interpretacji.

### 5.6 `--commit` (D17, D26)

Domyślnie wyłączone: zmiany zostają w working tree, a raport mówi, co zacommitować.

Gdy `run.json.commit == true`, `finish`:

1. commituje **tylko** przy outcome `DONE` albo `DONE_PARTIAL`. Przy `BLOCKED`, `RED` i `ESCALATED` nie commituje nic;
2. stage'uje **wyłącznie** pliki testowe zmienione w tym przebiegu (pliki z raportów generacji plus pliki po resealu). Nigdy `git add -A`, nigdy nic spod `src/main`;
3. jeśli w stage'u są już cudze, niezwiązane zmiany, nie commituje i zapisuje w raporcie `commit skipped: index not clean`;
4. **wybiera branch** (niżej);
5. robi commit bez push, z wiadomością opisaną niżej („Wiadomość commita”);
6. zapisuje w `run-report.md` nazwę brancha i sha commita. Jeśli branch był nowy, raport mówi to wprost: „utworzono branch `tc-agent/AppointmentService/20260921-101500` od `master`; zmiany nie są na `master`”.

**Wiadomość commita (D27):**

```
test(AppointmentService): tc-agent DONE_PARTIAL [run 20260921-101500]

Added 9 characterization tests for AppointmentService.create and cancel,
covering the notice-period, horizon and inactive-offer guards. Two scenarios
are kept as @Disabled placeholders because the business-hours guard reads
LocalDateTime.now() directly; injecting a java.time.Clock would unblock them.
Existing tests for reschedule were only resealed - their behaviour did not change.

Mode: legacy | target: AppointmentService@4b1c2aa9
Tests: +9 new, 2 placeholders, 3 resealed, 0 human tests touched
Gates: branch coverage 84% (gate 80%), mutation 76% (gate 70%)
Suggestions: inject java.time.Clock into AppointmentService
Report: .test-agent/runs/AppointmentService/20260921-101500/run-report.md
```

Wiadomość ma trzy części:

1. **Tytuł** — stały format, składany przez skrypt.
2. **Podsumowanie prozą, 2–5 zdań** — pisze je **recenzent** w nowym polu `commit_summary` w review. To jedyna rola, która widziała plan, wygenerowane testy i wyniki bramek, a działa jako ostatnia przed ACCEPT. Reguły dla recenzenta: angielski, czas przeszły, bez nazw TC, bez spekulacji; mówi co dodano, co zostało świadomie pominięte i dlaczego, i co odblokowałoby resztę. Pole jest wymagane przy decyzji `ACCEPT` / `ACCEPT_PARTIAL`.
3. **Blok faktów** — składany przez skrypt z artefaktów przebiegu: tryb, sha targetu, liczby testów (nowe / zaślepki / reseal), bramki, sugestie, ścieżka do raportu. Te liczby nie pochodzą od LLM, więc zawsze zgadzają się z raportem.

Gdy przebieg kończy się `DONE` **bez recenzenta** (sam reseal albo planer zwrócił `COMPLETE`), nie ma `commit_summary`. Skrypt wstawia wtedy zdania z szablonu, np. „Resealed 3 characterization tests of AppointmentService after commit 4b1c2aa9; their behaviour did not change.”.

Ta sama proza trafia też na początek `run-report.md`, więc człowiek czytający raport i historię gita widzi ten sam opis.

**Wybór brancha:**

| bieżący stan | co robi agent |
|---|---|
| branch **niechroniony** | commituje na nim |
| branch **chroniony** | tworzy `tc-agent/<slug>/<run-id>` od bieżącego HEAD, przełącza się na niego (`git switch -c`), commituje tam |
| detached HEAD (typowe w Jenkinsie) | tak samo jak branch chroniony |
| branch `tc-agent/<slug>/<run-id>` już istnieje | nie commituje, `commit skipped: branch exists` (nie powinno się zdarzyć, bo run-id jest unikalny) |

Przełączenie brancha zabiera ze sobą wszystkie niezacommitowane zmiany z working tree, także cudze. Git tak działa i to nic nie psuje, ale raport o tym informuje. Agent nigdy nie wraca sam na poprzedni branch.

**Skąd agent wie, które branche są chronione.** Z `AGENTS.md` w katalogu głównym repo docelowego, z jednej linii w stałym formacie (czyta ją skrypt, a nie LLM):

```markdown
tc-agent-protected-branches: master, main, develop, release/*
```

- lista rozdzielona przecinkami, obsługiwane są globy (`release/*`);
- linia może stać w dowolnym miejscu pliku; jeśli jest kilka, liczy się pierwsza;
- **brak `AGENTS.md` albo brak tej linii → chroniony jest tylko `master`**;
- pusta lista (`tc-agent-protected-branches:` bez wartości) też oznacza tylko `master`. Nie da się wyłączyć ochrony `master` przez pomyłkę.

Push i ewentualny merge request są po stronie człowieka albo Jenkinsa.

---

## 6. Role po zmianach

### 6.1 tc-orchestrator

Nadal jest tylko dispatcherem, ale krótszym. Szkic docelowej treści (bez frontmattera):

```markdown
# Test Orchestrator Agent (Model B)

You dispatch; you do not judge. `$C` = `.github/agents/tc-agent/scripts`.

## Input
- `targets` — one slug or a list (`ClassName` or `ClassName.methodName`), passed through unchanged.
- `mode` (`legacy` default | `spec-driven`), `interactive` (default false), optional `spec`.
- `impl_cap` (default 3), `plan_cap` (default 2).

## Per target
1. Start the run — the ONLY place mode/interactive/spec/caps go:
   python $C/tc_orchestrate.py start <slug> --repo . --mode <mode> [--interactive] [--spec <path>] --impl-cap <n> --plan-cap <n>
   Remember the printed `run_id`.
2. Loop:
   python $C/tc_orchestrate.py state <slug> --run <run_id> --repo .
   and do exactly its `next_action`:
   | PLAN     | run_subagent tc-planner   — pass the slug and `dispatch.run_dir`, nothing else |
   | GENERATE | run_subagent tc-generator — the slug and `dispatch.run_dir` |
   | REVIEW   | run_subagent tc-reviewer  — the slug and `dispatch.run_dir` |
   | RESEAL   | python $C/tc_orchestrate.py reseal <slug> --run <run_id> --repo . |
   | FINISH   | python $C/tc_orchestrate.py finish <slug> --run <run_id> --repo . — then stop this target |
3. Show the user the `finish` output verbatim. Red tests first, when there are any.

## Never
- Read a plan, review or report to decide anything — `state` decides.
- Confirm a safety stop (freshness guard, NEEDS_TRIAGE, NEEDS_CLARIFICATION) for the user.
- Raise a cap. Edit any file. Run two roles at once for the same target.
- Commit anything.

## Resume
Same session: `state --run latest`. A new session starts a new run with `start` —
the world is re-derived; the old run folder stays for reading only.
```

Znika: przekazywanie `prior_*_path` i `carry_review_path`, ledger, zakaz „nie dawaj `--mode` do `state`” (mode trafia do `start`), sekcja `working_tree` (przeniesiona do `finish`).

### 6.2 tc-planner

| obszar | Model A | Model B |
|---|---|---|
| wejście | slug, mode, interactive, spec, ścieżki prior | slug i `run_dir`; mode, interactive i spec z `run.json` |
| Phase 0 (repo Maven / JUnit / JaCoCo) | zostaje | zostaje |
| Phase 1 (target, sha) | `git log %H`, freshness guard | sha `%h` z derive-state; **freshness guard znika z planera**, bo liczy go derive-state (§4.2). Z interactive planer zadaje pytanie potwierdzające świeży kod i zapisuje odpowiedź |
| Phase 2 (context pack) | `.test-agent/context/<slug>/` | `<run_dir>/context-pack.md` |
| konwencje | z `AGENTS.md` przez pack | czyta `tc-test-conventions.md` i sekcję REPO CONVENTIONS z packa; `implementation_hints.test_method` wg obowiązującej reguły nazewnictwa (D20, domyślnie `shouldXxxWhenYyy`) |
| Phase 2.5 (czytanie raportów) | tak | **znika** — zastępuje ją `derive-state.md` |
| Phase 3–5 (dowody, scenariusze, evidence_strength) | zostają | zostają. Zakres planu wyznacza derive-state: `NO_TESTS` → pełny plan, `COVERAGE_GAP`/`MUTATION_GAP` → scenariusze tylko dla niepokrytych linii i mutantów, `STALE` → re-charakteryzacja wskazanych metod |
| istniejące zaślepki | — | nie podnosi ich ponownie, chyba że znalazł **nowy** dowód (wtedy scenariusz `replaces: <zaślepka>`) |
| Phase 6 (wersjonowanie, delta) | plan-vN, osie, delta-integrity | `plan-v<N>` tylko w obrębie przebiegu, bez osi i bez delty |
| status `COMPLETE` | wszystko COVERED/REMOVED | **całą pozostałą lukę z derive-state wyjaśniają istniejące testy albo zaślepki** — nie ma nic do wygenerowania |

Nowe pola scenariusza: `replaces` (opcjonalny `Class#method` — test stale do przepisania albo zaślepka do zastąpienia) oraz lista `obsolete` w planie (testy, których zachowania już nie ma; tylko rekomendacja usunięcia).

### 6.3 tc-generator

| obszar | Model A | Model B |
|---|---|---|
| wejście | najwyższy plan, najnowsze review linii, carry | najwyższy plan w `run_dir` i najnowsze review w `run_dir` (jeśli jest) |
| tabela `change` × `implementation` | tak | **znika**. Reguła: każdy scenariusz → test; każdy `deferred` → zaślepka; `replaces` → przepisz wskazaną metodę; scenariusz niemożliwy → zaślepka z powodem |
| znakowanie | `// TC-nn`, `// AI GENERATED`, `// CHARACTERIZATION` | Javadoc z §3. `@characterizes` bierze sha z `plan.context.target_sha`; `@mode` i `@interactive` z `run.json` |
| klasa testowa | — | bez tagów klasowych (D6). Jeśli klasa nie istnieje, tworzy ją wg `implementation_hints.test_file` |
| styl kodu | z `AGENTS.md` repo przez pack | `tc-test-conventions.md` (nazwy, `given/when/then`, czas, mocki, asercje), nadpisane tam, gdzie REPO CONVENTIONS w packu mówi inaczej (D19) |
| review feedback, `scope` | zostaje | zostaje (mapowanie po `test_method`, a nie po TC) |
| SKIPPED w rundzie naprawczej | „`// TC-nn` istnieje” | „metoda `test_method` istnieje, a review jej nie wskazuje” |
| OBSOLETE | wynik generatora | znika z generatora; `obsolete` z planu trafia prosto do raportu przez `finish` |
| statusy w raporcie | IMPLEMENTED / BLOCKED / SKIPPED / OBSOLETE | `IMPLEMENTED` / `PLACEHOLDER` / `SKIPPED` |
| `get_errors`, zakaz uruchamiania | zostaje | zostaje |

`PLACEHOLDER` wymaga `reason` i `test_method` (nazwy zaślepki). BLOCKED jako status znika, bo scenariusz niemożliwy kończy w kodzie jako zaślepka. Niezmiennik: każdy scenariusz ma w kodzie metodę.

### 6.4 tc-reviewer

| obszar | zmiana |
|---|---|
| wejście | plan, raport i poprzednie review z `run_dir` |
| krok 1 (testy) | `tc_run_tests.py` sam znajduje klasy (D11), zamiast brać je z raportu |
| Stage 1 — konformancja | każdy scenariusz → metoda o nazwie `test_method` istnieje; `IMPLEMENTED` → test aktywny; `PLACEHOLDER` → `@Disabled("AI deferred: …")` z pustym ciałem i `@deferred`; Javadoc ma `@aiGenerated`, `@mode` zgodny z `run.json`, `@interactive` zgodny z `run.json`, w legacy `@characterizes <Class>@<sha>` zgodny z `target_sha`; brak `// TC-nn` i tagów na klasie |
| findingi | `missing_characterization_marker` zastąpiony przez `metadata_defect` (który tag, jaka metoda) |
| konwencje | Stage 2 sprawdza obowiązującą regułę nazewnictwa i strukturę sekcji (domyślne agenta albo nadpisane przez repo). Naruszenie = finding `convention` ze `scope: "test"`. Naruszenie reguły **integralności** (metadane, zaślepki) jest w Stage 1 i nie jest „stylem” |
| atrybucja | uncovered / survivor na linii scenariusza `IMPLEMENTED` → REPAIR_IMPLEMENTATION; na linii zaślepki → `unimplementable`, poza bramką; brak scenariusza → REPAIR_PLAN |
| sprawdzenia COVERED / REMOVED | znikają razem z osiami |
| decyzje i `repeated` | bez zmian (repeated liczone w obrębie przebiegu) |
| `commit_summary` | przy ACCEPT / ACCEPT_PARTIAL pisze 2–5 zdań podsumowania przebiegu (§5.6). Trafia do wiadomości commita i na początek `run-report.md` |

### 6.5 tc-contracts.md

- §1 Artefakty — zostaje, lista artefaktów rozszerzona o `run.json`, `derive-state.md` i `run-report.md`.
- §2 Nazwy i wersje — **przepisane**: katalog przebiegu, numeracja tylko w przebiegu, „nigdy nie czytaj innego przebiegu”.
- §3 Dwie osie — **usunięte**. W to miejsce: „Metadane w kodzie” (skrót §3 tego planu) i niezmiennik „każdy scenariusz kończy w kodzie”.
- §4 Skrypty — zostaje (czarna skrzynka, exit 0/1/2).
- **§5 Konwencje (nowy)** — „Przed napisaniem lub oceną testu przeczytaj `tc-test-conventions.md` oraz sekcję REPO CONVENTIONS z context-packa. Pierwszeństwo: integralność > repo > domyślne agenta”. `tc-contracts.md` czytają wszystkie role jako pierwszy plik, więc to jedno odwołanie wystarczy, żeby każda rola wiedziała o konwencjach.

---

## 7. Skrypty — zmiany plik po pliku

| plik | zmiana |
|---|---|
| `tc_common.py` | **nowe:** `resolve_target(repo, slug)`, `discover_test_classes(repo, target)`, `run_dir(repo, slug, run)`, `load_run(run_dir)`. `checks_dir` przechodzi do `<run_dir>/checks`. `load_plan` / `load_report` zostają tylko dla ról, skrypty sprawdzające z nich nie korzystają. `resolve_module` bez parsowania prozy z `context.notes` (moduł z systemu plików) |
| `tc_git.py` **nowy** | `short_sha(file)`, `is_dirty(file)`, `age_days(file)`, `sha_matches(a, b)` (prefiks, min. 7) |
| `tc_javadoc.py` **nowy** | parser z §3.7 oraz `reseal(file, method, old, new)` (podmiana jednej linii) |
| `tc_derive_state.py` **nowy** | §4. Logika decyzji to czysta funkcja `decide(tier1, tier2, tier3, guard)`, testowalna bez Mavena |
| `tc_orchestrate.py` | przepisany: `start` / `state` / `reseal` / `finish` (§5). Usunięte `ledger`, `clean`, `open_feedback_review`, `scenarios_in_scope`, carry |
| `tc_run_tests.py` | `<slug> --repo . --run-dir <d> --label <entry\|r1…> [--repeat N]`; klasy z `discover_test_classes`; `--tests` zostaje jako override |
| `tc_coverage.py` | target z `resolve_target`, gate z profilu, exec z `<run_dir>/checks`; `--label` zamiast `--iteration` |
| `tc_mutation.py` | jak wyżej, testy z discovery |
| `tc_build_context.py` | zapis do `<run_dir>/context-pack.md`; przy każdym EXISTING TEST krótki nagłówek z liczbą metod `@aiGenerated` i zaślepek; usunięte `.test-agent/conventions.md`. **Sekcja REPO CONVENTIONS** zbudowana wg §10.3: pliki instrukcji repo, filtrowanie `.instructions.md` po `applyTo`, nagłówek z zasadą pierwszeństwa. Gdy repo nie ma żadnych instrukcji, pack mówi to wprost („none — agent defaults apply”) |
| `tc_evidence_strength.py`, `tc_verify_refs.py`, `tc_validate_plan.py`, `tc_md_payload.py` | bez zmian logiki, tylko ścieżki |

---

## 8. Schematy

| schemat | zmiana |
|---|---|
| `tc-test-plan.schema.json` | **usunięte:** `based_on_version`, scenariusz `change`, `implementation`, `covered_by`, `split_from`, `change_reason`, `MISLABELLED_REMOVED`. **Wymagane:** `implementation_hints.test_method` i `test_file` (klucz traceability). **Nowe:** `replaces`, `deferred[].placeholder_method`, `obsolete[]`. `context.target_sha` jako `%h` (min. 7 znaków) |
| `tc-generation-report.schema.json` | statusy `IMPLEMENTED` / `PLACEHOLDER` / `SKIPPED`; `test_method` wymagane zawsze |
| `tc-review.schema.json` | usunięte sprawdzenia COVERED/REMOVED; finding `metadata_defect`; nowe pole `commit_summary` (string, wymagane przy `ACCEPT` / `ACCEPT_PARTIAL`); reszta bez zmian |
| `tc-project-profile.schema.json` | nowe `freshness_days` (int, domyślnie 7) i `instruction_paths` (lista ścieżek z repo, także spoza `.github`, np. `docs/code-conventions.instruction.md`) |
| `tc-derive-state` / `tc-run` | bez schematu JSON — oba pisze skrypt, a kształt pilnują dev-testy |

---

## 9. Pliki w repo po zmianach

```
.github/agents/tc-agent/
  tc-contracts.md                  przepisany (§6.5)
  tc-test-conventions.md           NOWY — domyślne konwencje testów agenta (§10)
  tc-orchestrator.agent.md         przepisany (§6.1)
  tc-planner.agent.md              przepisany (§6.2)
  tc-generator.agent.md            przepisany (§6.3)
  tc-reviewer.agent.md             zmieniony  (§6.4)
  tc-project-profile.md            + freshness_days, instruction_paths
  tc-requirements.txt              bez zmian
  schemas/                         §8
  scripts/
    tc_common.py                   zmieniony
    tc_git.py                      NOWY
    tc_javadoc.py                  NOWY
    tc_derive_state.py             NOWY
    tc_orchestrate.py              przepisany
    tc_build_context.py            zmieniony
    tc_run_tests.py                zmieniony
    tc_coverage.py                 zmieniony
    tc_mutation.py                 zmieniony
    tc_evidence_strength.py        ścieżki
    tc_verify_refs.py              ścieżki
    tc_validate_plan.py            bez zmian
    tc_md_payload.py               bez zmian
  tools/
    tc_test_javadoc.py             NOWY
    tc_test_derive_state.py        NOWY
    tc_test_run_state.py           NOWY  (zastępuje tc_test_orchestrate.py)
    tc_smoke_pipeline.py           zaktualizowany
    tc_check_examples.py           zaktualizowany
    tc_test_orchestrate.py         USUNIĘTY
AGENTS.md                          reguły agenta usunięte; zostaje tylko odnośnik dla ludzi (§10.6)
docs/MODEL-B-SPEC.md               zaktualizowany decyzjami (D1–D17)
docs/MODEL-B-PLAN.md               ten plik
```

`_agent-fixes/` — nie ruszam go i nie traktuję jako źródła, bo zawiera starsze wersje. Możesz go usunąć, kiedy zapis do `.github` będzie stabilny.

---

## 10. Konwencje testów: agent kontra repo (D18–D22)

### 10.1 Problem

Dziś reguły, bez których agent nie działa poprawnie, są w `AGENTS.md` repozytorium `tests-app`: znakowanie testów AI, znaczenie testów charakteryzujących i dyscyplina czasu. Na innym repozytorium tego pliku nie ma, więc agent traci te reguły i nie ma o tym pojęcia. Część tej treści dotyczy przy tym wyłącznie tego repo (np. „produkcja woła `LocalDateTime.now()` bez Clock”).

Zasada Modelu B: **wszystko, czego agent potrzebuje, żeby działać poprawnie, jedzie z agentem.** Repo może tylko **dostroić styl**.

### 10.2 Trzy warstwy (D19)

| warstwa | źródło | przykłady | czy repo może zmienić |
|---|---|---|---|
| **1. Integralność pipeline'u** | `tc-contracts.md` i `tc-test-conventions.md` §A | Javadoc z tagami (§3), zaślepki `@Disabled` + `@deferred`, zero wymyślonych danych biznesowych, każdy scenariusz kończy w kodzie, zero testów zależnych od zegara, niczego pod `src/main`, nie mockuj klasy testowanej | **nie** — plik repo, który próbuje to zmienić, jest ignorowany w tym punkcie, a pack odnotowuje konflikt |
| **2. Instrukcje repo docelowego** | pliki instrukcji repo (§10.3) | „nazywamy testy `method_expected_condition`”, „bez komentarzy given/when/then, używamy BDDMockito”, „repozytoria przez Testcontainers, nie mocki” | — |
| **3. Domyślne agenta** | `tc-test-conventions.md` §B | `shouldXxxWhenYyy`, `// given / when / then`, AssertJ, mock repozytoriów | tak, każda reguła z §B |

Konflikty rozstrzyga się punkt po punkcie. Jeśli repo nadpisuje tylko nazewnictwo, sekcje `given/when/then` dalej obowiązują z warstwy 3.

### 10.3 Skąd agent bierze instrukcje repo

`tc_build_context.py` składa sekcję **REPO CONVENTIONS** w context-packu. Źródła, w tej kolejności:

1. `.github/copilot-instructions.md`,
2. `.github/instructions/*.instructions.md` — tylko pliki, których `applyTo` (glob z frontmattera) pasuje do ścieżki pliku testowego **albo** targetu; plik bez `applyTo` jest brany zawsze,
3. `AGENTS.md` w katalogu głównym,
4. dodatkowe ścieżki z `tc-project-profile.md` → `instruction_paths` (także spoza `.github`, np. `docs/code-conventions.instruction.md`).

Nagłówek sekcji w packu:

```
## REPO CONVENTIONS (repo-provided — style/naming only, NOT behavioural evidence)
Precedence: pipeline integrity (tc-contracts.md, tc-test-conventions.md §A) > these files > agent defaults (tc-test-conventions.md §B).
A rule here that contradicts §A is void.
Sources: .github/copilot-instructions.md, .github/instructions/testing.instructions.md (applyTo: src/test/**)
```

Gdy repo nie ma żadnego z tych plików: `REPO CONVENTIONS: none found — agent defaults (tc-test-conventions.md §B) apply.`

Nie polegamy na tym, że host (Copilot) sam wstrzyknie instrukcje repo do subagenta, bo to zachowanie jest nieudokumentowane (spec §10). Pack jest kanałem pewnym.

### 10.4 Kto co czyta

| rola | `tc-contracts.md` | `tc-test-conventions.md` | REPO CONVENTIONS (pack) | po co |
|---|---|---|---|---|
| orchestrator | tak | nie | nie | nie pisze i nie ocenia testów |
| planner | tak | tak (§B1 nazewnictwo) | tak | wypełnia `implementation_hints.test_method` wg obowiązującej reguły nazewnictwa |
| generator | tak | tak (całość) | tak | pisze kod |
| reviewer | tak | tak (całość) | tak | Stage 1 sprawdza §A, Stage 2 sprawdza §B z nadpisaniami repo |

Każda rola czyta `tc-contracts.md` jako pierwszy plik, a jego nowa §5 odsyła do `tc-test-conventions.md`. Dzięki temu nie ma ryzyka, że któraś rola „nie wie”, nawet jeśli jej własny prompt tego nie powtórzy.

**D22** Nadpisać domyślne reguły może **tylko jawna instrukcja**. Jeśli istniejąca klasa testowa ma metody w innym stylu, a repo nie ma instrukcji, agent i tak pisze `shouldXxxWhenYyy`, więc w jednej klasie mogą być dwa style. Recenzent nie zgłasza starych metod jako naruszenia, bo ocenia tylko metody `@aiGenerated`.

### 10.5 Treść `tc-test-conventions.md` (pełna propozycja)

```markdown
# Test conventions (tc-agent)

Repo-agnostic conventions for every test this pipeline writes or reviews. They
travel with the agent, so they apply in any repository.

Precedence, rule by rule:
  §A pipeline integrity  >  repo instructions (REPO CONVENTIONS in the context pack)  >  §B defaults
A repo instruction may replace any §B rule. It can never relax an §A rule; when it
tries, follow §A and mention the conflict in your report's notes.

## §A — Pipeline integrity (not overridable)

A1. Metadata. Every test method you write carries a Javadoc: one prose line, then
    one tag per line. Tags on METHODS only — never on the test class.
      @aiGenerated                      always
      @mode legacy | spec-driven        always (from run.json)
      @interactive                      when run.json says so
      @characterizes <Class>@<sha>      legacy only; sha = plan.context.target_sha
      @note <text>                      optional, repeatable; about THIS test
    Never add these tags to a method you did not write.

A2. Placeholders. A scenario that is deferred, or that you cannot implement
    soundly, becomes an empty method with the same metadata plus
    `@deferred <reason>` and `@Disabled("AI deferred: <short reason>")`.
    Every plan scenario ends up in the code as a test OR a placeholder.

A3. Characterization. A legacy test freezes what the code did at <sha>, bugs
    included. It asserts current behaviour, never "correct" behaviour. Its
    first Javadoc line says so.

A4. Data. Every business value comes from the plan's evidence (builders,
    fixtures, seeders, the code itself in legacy). No invented values.

A5. Determinism. No test may depend on the wall-clock time, the date, random
    values, execution order or sleeps.
    - When production code reads the clock directly, build times RELATIVE to now
      and make them satisfy every guard that precedes the one under test.
    - When a branch cannot be made deterministic without a code seam, write a
      placeholder (A2) and a suggestion ("inject java.time.Clock ..."). A flaky
      test is the worst possible output.

A6. Boundaries. Never modify production code. Never mock the class under test.

A7. One scenario, one method. A parameterized test may cover sibling scenarios
    of the same shape; its Javadoc then lists each covered scenario in @note.

## §B — Defaults (overridable by repo instructions)

B1. Method names: lowerCamelCase, `should<Outcome>When<Condition>`, no
    underscores, no `test` prefix.
      shouldThrowNotFoundWhenOfferDoesNotExist
      shouldSaveScheduledAppointmentWhenRequestIsValid
    Without a meaningful condition: `should<Outcome>` (shouldReturnAllActiveOffers).

B2. @DisplayName: the scenario description, in plain English.

B3. Structure: three commented sections, separated by a blank line.
      // given
      // when
      // then
    For an exception assertion, where act and assert are one statement:
      // when & then
      assertThatThrownBy(() -> service.create(request))
          .isInstanceOf(ApiException.class)
          .extracting("status").isEqualTo(HttpStatus.NOT_FOUND);
    Placeholders (A2) have no sections — the body is empty.

B4. Assertions: AssertJ when it is on the classpath, otherwise JUnit 5
    assertions. An exception assertion checks the type AND the property that
    tells it apart (status, code, message) — never a bare "throws".

B5. Collaborators: mock repository/gateway classes (the database or network
    boundary) with Mockito; build real domain objects, DTOs and value types.

B6. Setup: extract a private helper for construction repeated across tests
    (validRequest(), activeOffer()) instead of repeating it.

B7. Test class: `<Target>Test` in the same package under the test root, unless a
    test class for the target already exists — then add to it.
```

### 10.6 Co się dzieje z `AGENTS.md` w `tests-app`

Wszystkie reguły z dzisiejszego pliku przechodzą do agenta:

| dzisiejsza sekcja `AGENTS.md` | dokąd |
|---|---|
| Marking generated tests (`// AI GENERATED`) | §A1 (Javadoc zamiast komentarza) |
| Characterization tests | §A3 |
| Time and determinism — reguła ogólna | §A5 |
| Time and determinism — „produkcja woła `LocalDateTime.now()` bez Clock” | nigdzie: to fakt o kodzie, który agent i tak widzi w context-packu |
| „quarter-aligned time about now+30min”, „now+91 days” | nigdzie jako reguła. To przykłady dla guardów tego repo, które wynikają z kodu i dowodów w planie |

W `tests-app` `AGENTS.md` **zostaje z sekcji testowych opróżniony**. Zostaje w nim tylko krótka informacja dla ludzi („testy w tym repo generuje tc-agent; konwencje: `.github/agents/tc-agent/tc-test-conventions.md`”) oraz ewentualnie linia `tc-agent-protected-branches:` (§5.6). To konfiguracja repo, a nie reguła pisania testów, więc nie narusza zasady, że konwencje testów należą do agenta. Dzięki temu repo nie ma nadpisań i agent działa na swoich domyślnych regułach, czyli dokładnie tak, jak będzie działał na nowym repo.

Nadpisania repo testuje osobny scenariusz akceptacyjny E13 na tymczasowym pliku instrukcji.

---

## 11. Scenariusze akceptacyjne (end-to-end, uruchamiasz Ty)

Uruchamiane na `tests-app` na gałęzi `model-b`. Każdy ma oczekiwany outcome.

| # | scenariusz | przygotowanie | oczekiwany wynik |
|---|---|---|---|
| E1 | pierwszy przebieg legacy | `AppointmentService` bez testów AI, commit ≥ 7 dni | `NO_TESTS` → PLAN → GENERATE → REVIEW → `DONE` / `DONE_PARTIAL`; testy z Javadociem, zaślepki dla guardów czasowych |
| E2 | powtórka bez zmian | zaraz po E1, po commicie testów | derive-state `DONE` (albo PLAN → planer COMPLETE → `DONE_PARTIAL`, gdy są zaślepki); **żadnych nowych testów** |
| E3 | Case 1 — zmiana kodu bez zmiany zachowania | refaktor w targecie, commit | stale i zielone → `RESEAL` → `DONE`; w diffie tylko podmiana sha |
| E4 | Case 1 — nowa gałąź w kodzie | dopisany warunek, commit (+ interactive, bo commit jest świeży) | `COVERAGE_GAP` → plan tylko dla nowej gałęzi |
| E5 | zmiana zachowania | zmieniona wartość zwracana, commit, interactive | stale i czerwone → `recharacterize` → przepisany test z nowym sha |
| E6 | freshness guard | świeży commit targetu, legacy, bez interactive | `BLOCKED` (`TARGET_TOO_FRESH`), raport w `run-report.md`; nic w kodzie |
| E7 | dirty | niezacommitowana zmiana w targecie, legacy | `BLOCKED` (`TARGET_DIRTY`) |
| E8 | Case 2 — testy ludzkie | ludzki test pokrywający część klasy | plan tylko dla luk; ludzkie testy nietknięte |
| E9 | czerwony test ludzki | celowo zepsuty ludzki test | `RED`, raport z lokalizacją; nic nie wygenerowane |
| E10 | zespół / CI | świeży klon bez `.test-agent/` po E2 | identyczny wynik derive-state jak lokalnie |
| E11 | spec-driven | ten sam target, `--mode spec-driven --spec …` | testy bez `@characterizes`; E3 go nie dotyczy |
| E12 | target metodowy | `AppointmentService.create` po zmianie innej metody | `RESEAL` odświeża sha; brak pętli PLAN |
| E13 | nadpisanie konwencji przez repo | tymczasowy `.github/instructions/testing.instructions.md` z `applyTo: "src/test/**"`: „nazwy `method_expected_condition`, bez komentarzy given/when/then” | nowe testy w tym stylu; Javadoc z tagami **bez zmian**; review bez findingów `convention` |
| E14 | repo próbuje wyłączyć integralność | ten sam plik z „nie dodawaj Javadoca do testów” | Javadoc z tagami jest mimo to; konflikt odnotowany w `notes` raportu generacji |
| E15 | brak instrukcji repo | `tests-app` po opróżnieniu `AGENTS.md` | REPO CONVENTIONS w packu zawiera tylko odnośnik z `AGENTS.md`, bez nadpisań; testy `shouldXxxWhenYyy` z `// given / when / then` |
| E16 | `--commit` na `master` bez linii w `AGENTS.md` | przebieg DONE na `master` | nowy branch `tc-agent/<slug>/<run-id>`, commit tylko z plikami testowymi, `master` bez zmian |
| E17 | `--commit` na branchu niechronionym | `AGENTS.md`: `tc-agent-protected-branches: master, develop`, przebieg na `feature/x` | commit na `feature/x` |

`SimpleCalculatorService` był niedawno modyfikowany, więc jest naturalnym kandydatem do E6.

---

## 12. Etapy wdrożenia

Każdy etap kończy się moim krótkim podsumowaniem i Twoją weryfikacją, zanim ruszę dalej.

| etap | zakres | kryterium ukończenia | gdzie testowane |
|---|---|---|---|
| 0 | tag Modelu A | ✅ istnieje | — |
| 1 | `docs/MODEL-B-SPEC.md` zaktualizowany o D1–D17 | spec i ten plan są spójne | przegląd |
| 2 | `tc_git.py`, `tc_javadoc.py`, zmiany w `tc_common.py` (target, discovery, run dir) | testy jednostkowe zielone: parser na próbkach (w tym nawiasy w `@DisplayName`, parametryzowane, zaślepki, tagi zniekształcone), porównanie prefiksu sha, reseal jednej linii | u mnie, na sztucznym repo git |
| 3 | `tc_derive_state.py` | testy `decide()` na wszystkich wierszach z §4.2 i guardzie; tier 1 na sztucznym repo z commitami (stale, dirty, wiek) | u mnie |
| 4 | `tc_orchestrate.py` start / state / reseal / finish (+ `--commit`) | testy maszyny stanów z §5.4 (każdy wiersz) na spreparowanych artefaktach; commit na sztucznym repo: tylko przy DONE, tylko pliki testowe, odmowa przy brudnym indeksie; branche chronione: brak `AGENTS.md` → nowy branch z `master`, lista z globem, detached HEAD, pusta lista, branch niechroniony → commit na miejscu | u mnie |
| 5 | `tc_run_tests.py`, `tc_coverage.py`, `tc_mutation.py`, `tc_build_context.py` bez planu, sekcja REPO CONVENTIONS z filtrowaniem `applyTo` | `--help` i dry-run na sztucznym repo; build context na kopii `tests-app`; testy filtrowania `applyTo` (pasuje / nie pasuje / brak frontmattera) | u mnie (bez Mavena), Maven u Ciebie |
| 6 | schematy | `tc_check_examples.py` przechodzi na przykładach z promptów | u mnie |
| 7 | agenci, `tc-contracts.md`, **`tc-test-conventions.md`**, `AGENTS.md` (opróżnienie), profil | przykłady JSON w promptach walidują się schematami; spójność nazw komend; żadna reguła z §A nie jest powtórzona w promptach ról w sprzecznej wersji | przegląd |
| 8 | narzędzia dev (smoke, check_examples), usunięcie `tc_test_orchestrate.py` | wszystkie dev-testy zielone | u mnie |
| 9 | end-to-end E1–E12 | wyniki zgodne z §11 | **u Ciebie** (Maven, Copilot) |

**Ograniczenie operacyjne:** shell na Twoim komputerze nie działa (aktualizacja Windows). Pliki przenoszę narzędziami stage/commit, a Pythona testuję u siebie. Jeśli zapis do `.github` zostanie odrzucony, wrzucam pliki do `_agent-fixes/` z tą samą strukturą i mówię, co skopiować.

---

## 13. Ryzyka i otwarte kwestie

| # | ryzyko | mitygacja |
|---|---|---|
| R1 | Koszt: każdy przebieg z testami buduje i uruchamia testy (tier 2), a przy zielonym coverage także PIT | Warstwy (D3). Przy DONE_PARTIAL z lukami, które wyjaśniają zaślepki, każdy przebieg kosztuje dodatkowo jedno wywołanie planera. Jeśli to będzie bolało, można dodać „pieczęć” zaślepki na liniach — świadomie odłożone |
| R2 | Discovery po nazwie klasy łapie też testy, które tylko wspominają target (np. w stringu) | Zawyża tylko zestaw uruchamianych testów, a nie wynik coverage. Akceptowalne |
| R3 | Człowiek usuwa zaślepkę bez powodu → pipeline ponownie zapyta / odroczy | Świadomy trade-off „zero plików” (spec §13) |
| R4 | Sha per plik → szum przy dużych klasach | Reseal (D15). Bez niego: szum idzie do planera |
| R5 | Parser Javadoc na nietypowym formatowaniu (Javadoc po adnotacjach, komentarze w środku) | Nierozpoznane metody z `@aiGenerated` w treści trafiają do `metadata_defects`, a nie znikają po cichu |
| R6 | Testy z konwencją Modelu A (`// TC-nn`) w innych repo | Traktowane jak ludzkie. Opcjonalny skrypt migracyjny, poza zakresem |
| R7 | Bez `--commit` kolega nie widzi nowych testów przed ręcznym commitem | Zgodne z D1; `run-report.md` mówi wprost „zacommituj”; w CI `--commit` |
| R8 | `%h` przy małym repo może mieć 7 znaków, a przy dużym 9+ | Porównanie po prefiksie (D10), zapis zawsze w pełnym `%h` z chwili generacji |
| R9 | Jenkins workspace rośnie o katalogi przebiegów | Czyszczenie workspace to zadanie Jenkinsa; pipeline nigdy nie czyta starych przebiegów |

**Rozstrzygnięte przy weryfikacji (2026-09-21):** reseal automatyczny (D15), mode w `start` (D16), dirty zawsze BLOCKED (D4a), opcjonalny `--commit` z regułami §5.6 (D17), zaślepka przy nienaprawionym błędzie kompilacji (D23), domyślny styl agenta także w klasach o innym stylu (D22), nowa klasa `<Target>Test` (D24), `AGENTS.md` jako sam odnośnik (D25), branche chronione z `AGENTS.md`, domyślnie tylko `master` (D26), wiadomość commita z podsumowaniem od recenzenta (D27).

Otwartych decyzji nie ma. Następny krok: etap 1 (aktualizacja `MODEL-B-SPEC.md`).

---

## 14. Wdrożenie — odchylenia i uzupełnienia względem planu

- **Stale zaślepka** trafia do `recharacterize` (planer ocenia ją na nowo; jeśli nadal nie da się jej zaimplementować, generator odświeża jej sha). Wynika to z §3.5; koszt opisany w specu §12.
- **Schemat planu:** `COMPLETE` wymaga pustych `scenarios`/`deferred` i pola `gap_explanation`; `BLOCKED` wymaga `reason`; scenariusz i deferred mają pole `notes` (→ linie `@note`); deferred ma `placeholder_method` i opcjonalny `test_file`.
- **Etykiety checków:** skrypty przyjmują `--run <id|latest> --label <entry|v<N>-r<M>>`; exec JaCoCo jest per etykieta (`jacoco-<label>.exec`), więc wejściowy derive-state i review nie nadpisują sobie danych.
- **`finish` jest idempotentny** — drugie wywołanie pokazuje zapisany raport, nie commituje ponownie. Odmawia (exit 2), gdy `state` nie jest jeszcze `FINISH`.
- **Dev-testy (bez Mavena):** `tc_testkit.py` (wspólny harness + fixture'owe repo git), `tc_test_javadoc.py`, `tc_test_derive_state.py`, `tc_test_run_state.py`, `tc_test_build_context.py`, `tc_test_check_scripts.py` + `tools/fake_mvn/mvn` (prawdziwe skrypty sprawdzające napędzane fałszywym `mvn`, który pisze raporty surefire/JaCoCo/PIT). `tc_smoke_pipeline.py` przepisany pod katalogi przebiegów (prawdziwy Maven).
- **Maven w chmurze niedostępny** (Maven Central zablokowany polityką sieci), więc prawdziwy build nie był uruchomiony — pełen przebieg zasymulowałem na kopii `tests-app` przez fałszywy `mvn` (Case 1: reseal → DONE → commit na nowy branch).
