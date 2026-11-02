# tc-agent — Model B3: plan naprawczy po przeglądzie

> **Status:** etapy 0–6 wdrożone 2026-10-10 na gałęzi `model-b3` (commity „tc-agent B3 E0…E5”); akceptacja
> §6 (E26–E40, prawdziwy Maven + Copilot) po stronie użytkownika — E38 decyduje o etapie 3b.
> **Numeracja decyzji** kontynuuje `docs/MODEL-B2-PLAN.md` (od D84).
> **Gałąź:** `model-b3` od `final-review`. **Punkt powrotu:** tag `model-b2-final` (etap 0).
> **Charakter:** refaktor naprawczy. Główne zachowanie agenta się nie zmienia; każda poprawka zastępuje
> istniejący tekst lub kod, zamiast dopisywać obok.

---

## 0. Zasady

1. **Bez zmiany zachowania głównego.** Zostają: derive-state, maszyna stanów w skryptach, metadane w Javadocu,
   reseal, trzy role z niezależnym recenzentem, bramki i atrybucja, limit rund.
2. **Pliki nie rosną.** Budżet liczony `wc -l` przed i po (§5). Nowa reguła zastępuje starą albo nie powstaje.
3. **Każda poprawka kodu ma test regresji** w istniejącym `tools/tc_test_*.py`, który pada na obecnej wersji.
4. Każdy etap zostawia działający pipeline: dev-testy zielone, `tc_check_examples` OK.

## 1. Co musi działać po zmianach (wymagania użytkownika)

| # | opcja | jak |
|---|---|---|
| W1 | characterization, z `--interactive` lub bez | bez zmian |
| W2 | spec-driven, z `--interactive` lub bez; bez podanej spec orchestrator o nią dopytuje | F3 |
| W3 | oba tryby z `--commit` | bez zmian, commit uszczelniony (F1) |
| W4 | pętla plan → generate → review, maksimum z pliku | `max_rounds` w `profile.md` (`--max-rounds` zostaje jako nadpisanie na jeden przebieg) |

## 2. Ustalenia z przeglądu (2026-10-10)

- **Spec-driven = tylko spec.** Testy powstają wyłącznie z wymagań opisanych w specyfikacji; przypadków
  nieopisanych nie pokrywamy (ani testem, ani zaślepką). Planer może dopytać (interactive) o dane, np.
  przykład numeru rachunku brokerskiego, i o niejasne lub sprzeczne warunki, np. co ma pierwszeństwo:
  flaga czy przynależność do listy.
- **Niejasna lub sprzeczna spec bez interactive** → planer zwraca `NEEDS_CLARIFICATION` (z cytatem obu
  fragmentów), przebieg kończy się `ESCALATED` bez testów. Tak jak dziś.
- **Czerwony istniejący test blokuje wszystko** — w obu trybach kończy przebieg `RED`.
- **Brudny target blokuje tylko characterization.** W spec-driven można testować kod w trakcie pisania.
- **Plan v2** powstaje tylko po `REPAIR_PLAN`; to, co zawiera, wynika z review (F15).
- **Jenkins** (przyszłość): tylko characterization bez interactive. Bez kodu na to teraz.
- **Anonimizacja** całego rozwiązania; publikowana będzie wersja finalna bez historii gita (po stronie użytkownika).
- `src/test` nieśledzony w `tests-app` to wypadek z testów rozwiązania — poza planem.
- Różne modele ról (generator `GPT-5.6 Luna`, reszta `Terra`) — świadomy wybór.
- `main` dopisany do domyślnie chronionych branchy.

## 3. Decyzje (D84–D106)

| # | F | obszar | ustalenie |
|---|---|---|---|
| D84 | F1 | Commit i zmiany poza testami | Commit tylko plików pod `**/src/test/**`. Zmiana poza `src/test` powstała w trakcie przebiegu → bez commita, `ESCALATED` z listą plików. `.test-agent/` pomijany zawsze, także bez wpisu w `.gitignore`. Zmiany sprzed `start` nie blokują i nigdy nie są commitowane. |
| D85 | F2 | `COMPLETE` | Dozwolony tylko w planie v1. W v2+ → `ESCALATED` („planer nie znalazł nic do naprawy — decyzja dla człowieka”). |
| D86 | F3 | Walidacja `start` | spec-driven bez `--spec` → exit 2 `SPEC_REQUIRED` (orchestrator pyta o ścieżkę i startuje ponownie). Nieistniejący `--spec` / `--test-data`, `profile.md` niezgodny ze schematem → exit 2 z powodem. |
| D87 | F4 | Brudny target | characterization: zawsze `BLOCKED`, sprawdzane w warstwie 1 (przed mavenem). spec-driven: dozwolony. |
| D88 | F5 | Flaky | `failures` = padł w każdym przebiegu, `flaky` = padł w części. Log mavena kolejnych prób dopisywany, nie nadpisywany. |
| D89 | F6 | Zakres metody | Lambdy metody wliczane do jej pokrycia i mutantów; nie ucinają zakresu linii. |
| D90 | F7 | Mutacje bez zainstalowanych zależności | Gdy check testów musiał użyć `-am`, mutacje od razu zgłaszają powód z komendą `mvn -DskipTests install -pl <moduł> -am`, bez wołania mavena. Skrypt sam nic nie instaluje. |
| D91 | F8 | Statusy PIT | Zbiór „wykrytych” statusów zgodny z PIT (do sprawdzenia w źródle PIT przy wdrożeniu). |
| D92 | F9 | `@Disabled` | `@DisabledOnOs`, `@DisabledIf…` itd. nie są czytane jako wyłączenie testu. |
| D93 | F10 | Wersja pluginu | `${właściwość}` rozwijana z `<properties>` pomu modułu i roota. |
| D94 | F11 | `resolve_target` | Indeks gita zamiast `rglob` (optymalizacja, bez zmiany zachowania). |
| D95 | F12 | Budżet packa | TARGET ma zarezerwowane miejsce jako pierwszy; SPEC przechodzi przez tę samą kontrolę budżetu; MANIFEST wylicza tylko to, co jest w packu. |
| D96 | F13 | Weryfikacja refów | Każdy ref w kształcie ścieżki (`plik[:linia]`) jest sprawdzany niezależnie od typu dowodu, także `human_decision` i refy w `data`. Odpowiedzi człowieka (nie-ścieżki) dalej pomijane. |
| D97 | F14 | Spec-driven cytuje spec | Każdy scenariusz i wpis `deferred` w spec-driven ma `requirement` i co najmniej jeden ref do pliku spec; inaczej `SPEC_REF_MISSING` („usuń scenariusz albo wskaż wymaganie”). Dowody dla DANYCH mogą pochodzić od człowieka. |
| D98 | F15 | Plan v2 | `REPAIR_IMPLEMENTATION`: ten sam plan, generator dostaje review i naprawia tylko wskazane metody (bez zmian). `REPAIR_PLAN`: v(N+1) = tylko zmiany — scenariusze dla luk z `feedback.plan` + `replaces` dla metod z `feedback.implementation`; generator dostaje v(N+1) BEZ review i realizuje go w całości, reszty nie rusza. |
| D99 | F16 | Zakres spec-driven | derive-state: testy (czerwone → `RED`), potem zawsze `PLAN (SPEC_REVIEW)`, bez coverage i PIT. Planer: tylko wymagania bez testu `tc-agent-spec`. Recenzent: niepokryte linie, których nie cytuje żaden scenariusz, to finding `minor` „poza spec” (nie `REPAIR_PLAN`); raport odsyła je do przebiegu characterization. Niejasność bez interactive: `NEEDS_CLARIFICATION` jak dziś. |
| D100 | F17 | Chronione branche | Domyślnie `["master", "main"]`. |
| D101 | F20 | Martwe pola schematów | Usunięte pola, których nie czyta żaden skrypt ani żadna rola (lista w etapie 3b). |
| D102 | F21 | `checks` w review | Review niesie tylko statusy checków (+ `flaky_only`). Liczby bramek `finish` czyta z `checks/*-<label>.md`; planer przy `REPAIR_PLAN` czyta niepokryte linie i mutanty wprost z tych plików (te same dane, z oryginału). Komunikaty kompilatora w findingu `compile_error`. |
| D103 | F22 | Opisy i format | Schematy bez `description` (treść ma właściciela w `references/` i `configuration.md`), z zachowanymi `errorMessage`; zapis zwarty. |
| D104 | F23 | Raport z planu | Jedno pole `reason` (wymagane dla `COMPLETE`, `BLOCKED`, `NEEDS_CLARIFICATION`) zamiast `gap_explanation` i `conflict`; `finish` pokazuje `reason` planu oraz pytania z `deferred[].question`. |
| D105 | F24 | Porządki w skryptach | Bez martwego kodu i duplikatów: `write_log`, `tc_git.changed`; wspólne `SKIP_DIRS` / `java_files` / `mentions` z `tc_common`; `mocked_only` jako wynik, nie atrybut funkcji; `stale_classes` liczone tylko w trybie `strict`. |
| D106 | F25 | Docstringi | Docstring funkcji = krótki opis, CO robi (zwykle jedno zdanie), bez historii incydentów i bez odwołań do decyzji. Docstring modułu = co robi + Usage + kody wyjścia (to jest `--help`). Komentarze tylko tam, gdzie kod sam nie mówi, co robi. |

---

## 4. Etapy

### Etap 0 — Start
1. Tag `model-b2-final`, gałąź `model-b3` od `final-review`.
2. Baseline: dev-testy zielone (460 asercji), `tc_check_examples` OK, liczby linii z §5.

### Etap 1 — Bezpieczeństwo przebiegu i commita (F1–F4)

**F1** — `tc_git.py`, `tc_orchestrate.py`
- `changed_contents` → migawka `{plik: hash}` wszystkich plików różnych od HEAD lub nieśledzonych, BEZ
  `**/src/test/**` i `.test-agent/**` (hash bez końcówek linii). Zastępuje `production_snapshot` (tylko `src/main`).
- `start` robi migawkę PRZED derive-state; `compute_state` porównuje przy każdym kroku i przy różnicy kończy
  `ESCALATED` z listą plików.
- `do_commit`: tylko pliki z segmentem `src/test/` w ścieżce; pozostałe z `test_files` nie są commitowane
  i trafiają do raportu.
- Testy: zmiana `pom.xml` w trakcie → `ESCALATED`, bez commita; plik w `.test-agent` bez `.gitignore` → ignorowany;
  `pom.xml` w `test_files` generatora → niezacommitowany; zmiana użytkownika sprzed startu → nie blokuje, nie trafia do commita.

**F2** — `tc_orchestrate.py`
- `compute_state`: `status == COMPLETE` i `plan_version > 1` → `FINISH / ESCALATED`.
- `render_report`: zdanie „reviewer accepted the gap” tylko gdy ostatnia decyzja to `ACCEPT_PARTIAL`.
- Test: `REPAIR_PLAN` → v2 `COMPLETE` → `ESCALATED`, brak commita.

**F3** — `tc_orchestrate.py`, `tc-orchestrator.agent.md`, `configuration.md`
- `cmd_start`: spec-driven bez `--spec` → exit 2 `SPEC_REQUIRED` (bez katalogu przebiegu); brak pliku
  `--spec` / `--test-data` → exit 2; `profile.md` walidowany schematem → exit 2 `INVALID_PROFILE` z listą naruszeń.
- Orchestrator: zdanie o `START_FAILED` rozszerzone o `SPEC_REQUIRED` → zapytaj o ścieżkę i uruchom `start` ponownie
  (zastąpienie istniejącej linii, nie nowy akapit).
- Testy: trzy przypadki odmowy.

**F4** — `tc_derive_state.py`
- characterization + target dirty / niezacommitowany → `BLOCKED` w warstwie 1, przed mavenem (także gdy bramki
  byłyby spełnione). Freshness bez zmian (tylko przy PLAN). spec-driven: dirty dozwolony.
- Test: dirty + zielone + bramki spełnione → `BLOCKED`, żaden check nie uruchomiony.

### Etap 2 — Pomiary (F5–F11)

**F5** — `tc_run_tests.py`, `tc_common.run`: `failures` = część wspólna porażek ze wszystkich przebiegów,
`flaky` = różnica; status `FAILED` tylko przy `failures`. `c.run(..., append=True)` dla kolejnych prób jednego checku.
Test: test pada raz, przechodzi raz → tylko `flaky`, status `PASSED`, exit 1; log zawiera obie próby.

**F6** — `tc_coverage.py`, `tc_mutation.py`: `method_ranges` pomija metody syntetyczne przy wyznaczaniu granic;
liczniki metody + jej `lambda$<metoda>$N`; mutacje: `mutatedMethod == metoda` lub `lambda$<metoda>$…`.
Test: metoda z lambdą — niepokryte linie lambdy widoczne, gałęzie lambdy w ratio.

**F7** — `tc_run_tests.py`, `tc_mutation.py`: payload testów zapisuje `also_make_used`; mutacje przy `true`
zwracają `SKIPPED_UNAVAILABLE` z komendą `install`, bez mavena; to samo przy rozpoznaniu braku zależności w wyjściu PIT.
Test: oba przypadki.

**F8** — `tc_mutation.py`: `KILLED` i liczenie survivorów zgodne z `DetectionStatus` PIT (sprawdzić w źródle
przy wdrożeniu; wynik zapisać w §7).

**F9** — `tc_javadoc.py`: `(?:Disabled|Ignore)\b`. Test: `@DisabledOnOs` → `disabled=False`.

**F10** — `tc_common.pom_plugin_version`: rozwinięcie `${x}` z `<properties>` (moduł, potem root); nierozwiązane → domyślna.
Test: `<jacoco.version>0.8.12</jacoco.version>` + `${jacoco.version}` → `0.8.12`.

**F11** — `tc_common.resolve_target`: obecność pomu przez `find_roots` / indeks gita zamiast `repo.rglob`.
Istniejące testy bez zmian.

**F24 — porządki w skryptach** (bez zmiany zachowania)
- usunąć `tc_common.write_log` (martwa) i `tc_git.changed` (alias `is_dirty`, przy okazji F1);
- `tc_build_context.py` i `tc_verify_refs.py`: `SKIP_DIRS`, `java_files`, `mentions` z `tc_common` zamiast własnych kopii;
- `discover_test_classes` zwraca `(found, mocked_only)` zamiast ustawiać atrybut funkcji (`tc_derive_state.tier1` dopasowany);
- `tc_run_tests.py`: `stale_classes` (spacer po całym `src/main` modułu) wywoływane tylko w trybie `strict`
  — w `auto` służyło wyłącznie komunikatowi; usunięty nieużywany parametr `agent_goals(goals)`;
- `tc_coverage.py`: jedna ścieżka logu zamiast trzech przypisań w bloku ponowienia;
- `docs/configuration.md`: jedno zdanie, że PIT liczy w jednym wątku, a `maven_args` z parametrem wątków PIT
  (nazwa do potwierdzenia przy wdrożeniu) to przyspiesza — bez nowego klucza profilu.
Pomiar przed zmianą (tests-app, bez mavena): części pythonowe 1–60 ms, cały context pack 0,16 s — czasu przebiegu
nie zmienia nic poza mavenem, więc F24 to porządek w kodzie, nie optymalizacja wydajności.
Bilans ≈ −40 linii. Testy: istniejące dev-testy bez zmian zielone; jeden test, że w `auto` `stale_classes` nie jest wołane.

### Etap 3 — Context pack i weryfikacja planu (F12–F14)

**F12** — `tc_build_context.py`: blok TARGET liczony i rezerwowany przed TEST DATA / DATA EXAMPLES / REPO CONVENTIONS /
SPEC; SPEC przez `add`-podobną kontrolę (przy braku miejsca: notatka); MANIFEST z listy faktycznie dodanych plików.
Test: duże instrukcje repo → TARGET w packu, pominięte pliki w NOTES, nie w MANIFEST.

**F13** — `tc_verify_refs.py`: `verify` sprawdza każdy ref w kształcie ścieżki bez względu na typ; refy w `data.*.ref` też.
Test: `human_decision: docs/spec.md:120` przy 40 liniach → `INVALID_EVIDENCE`; `human_decision: "odpowiedź na pytanie 2"` → pominięty.

**F14** — `tc_verify_refs.py`, `tc-test-plan.schema.json`: schemat — w spec-driven `requirement` wymagany w scenariuszach
i `deferred`; verify — w spec-driven każdy wpis ma ref do pliku spec z `run.json`, inaczej `SPEC_REF_MISSING`.
`tc_evidence_strength.py` bez zmian. Testy: scenariusz tylko z `implementation` w spec-driven → odrzucony;
scenariusz z ref do spec + dane od człowieka → OK.

### Etap 3b — Odchudzenie schematów (F20–F23), razem z F14

**Warunek:** zostaje tylko wtedy, gdy regresja (etap 6, E37–E40) pokazuje tę samą jakość dostarczania.
Robiony jako osobny commit, żeby w razie pogorszenia dało się go cofnąć jednym `git revert`.
Wersje robocze schematów (sprawdzone walidatorem na dopasowanych przykładach): `.test-agent/b3-schemas-draft/`.

**Zasada:** usuwamy pole tylko, gdy (1) nie czyta go żaden skrypt i (2) żadna rola nie ma instrukcji, by z niego
korzystać, albo ta sama informacja jest w pliku, który rola i tak czyta (`run.json`, `derive-state.md`,
`context-pack.md`, `checks/*.md`). Przed usunięciem każdego `description` jego treść jest porównana z plikiem-właścicielem;
to, czego tam nie ma, jest przenoszone, nie kasowane.

**F20 — martwe pola**
- plan: `target`, `interactive`, `characterization`, `priority`, `implementation_hints.test_class`,
  `context.source_roots` / `test_roots` / `related_classes` / `builders` / `fixtures` / `relevant_enums`,
  status `UNSUPPORTED_REPOSITORY` + `missing` (nieosiągalne — derive-state odrzuca repo bez pomu);
  `id` i `replaces` bez zbędnego `allOf`. `context.test_data[].used_by` ZOSTAJE.
- review: `generation_report`, `review_iteration`, `target`, `mode`, `stages`, `triage`, `findings[].id`,
  `findings[].stage`, typy `wrong_expected_behavior` i `data_not_backed_by_evidence`.
- raport generacji: `target`; `suggestions[].related` opcjonalne.

**F21 — `checks` bez kopii**
- review `checks` = `tests {status, reason, flaky_only}`, `coverage {status, reason}`, `mutation {status, reason}`;
  blok `compile` znika (jest `tests.status: COMPILE_ERROR`).
- `tc_orchestrate.collect`: bramki z `checks/coverage-<label>.md` / `mutation-<label>.md` ostatniego review
  (fallback: derive-state, jak dziś).
- planer: zdanie o `REPAIR_PLAN` wskazuje pliki checków z etykiety review zamiast `checks` review.
  Objętość dla planera (zmierzone na raportach tests-app): typowo 0,5–1 tys. tokenów, maksimum limitów skryptów
  (200 linii, 60 mutantów) ~6 tys. — przy packu do ~37 tys.
- recenzent: „quote the compiler lines” → w findingu `compile_error`; reguła decyzji 1 bez `stages`.

**F22 — opisy i format:** wszystkie `description` usunięte (po porównaniu z właścicielem), 6 `errorMessage` zostaje;
zapis zwarty (krótkie obiekty w jednej linii).

**F23 — `reason` w raporcie:** `reason` wymagane dla `COMPLETE` / `BLOCKED` / `NEEDS_CLARIFICATION`
(dla konfliktu w spec: cytat obu fragmentów); `finish` wypisuje `reason` planu także przy `COMPLETE`
i dokłada pytania z `deferred[].question` do listy pytań dla człowieka. Prompty planera i `modes/spec-driven.md`:
`conflict` / `gap_explanation` → `reason` (podmiana słowa, nie nowy tekst).

**Dopasowanie przykładów:** `modes/characterization.md`, `tc-generator.agent.md`, `tc-reviewer.agent.md` — bez usuniętych pól;
planer bez akapitu „Phase 0”, linii o `priority` i o `target`. `tc_check_examples.py` musi przejść.

**Wynik (policzony na wersjach roboczych):**

| schemat | dziś | po |
|---|---|---|
| plan | 617 | 159 |
| review | 577 | 136 |
| raport generacji | 135 | 50 |
| profil | 136 | 40 |
| **razem** | **1465 linii / 41 tys. znaków** | **385 linii / 15 tys. znaków** |

**Testy:** `tc_check_examples` na nowych schematach; plan spec-driven bez `requirement` → odrzucony; `COMPLETE` bez
`reason` → odrzucony; `finish` pokazuje `reason` i pytania z `deferred`; `collect` bierze bramki z plików checków;
dispatch `REPAIR_PLAN` + prompt planera wskazują pliki checków.

### Etap 4 — Prompty, bez wzrostu linii (F15–F17)

**F15** — `tc_orchestrate.py`, `tc-planner.agent.md`, `tc-generator.agent.md`
- Dispatch `GENERATE`: `review_path` tylko dla rundy naprawczej tego samego planu (r ≥ 2); pierwsza generacja vN → `null`.
- Planer: akapit „When `review_path` is set” przepisany na D98 (zastępuje „Keep what the previous plan delivered…”).
- Generator: „Repair round” bez zmian treści (działa teraz tylko w r ≥ 2).
- Test: po `REPAIR_PLAN` dispatch generatora dla v2 ma `review_path: null`; po `REPAIR_IMPLEMENTATION` — ścieżkę review.

**F16** — `tc_derive_state.py`, `modes/spec-driven.md`, `tc_orchestrate.render_report`
- derive-state spec-driven: warstwy 0–1, testy; czerwone (w tym stale characterization) / błąd kompilacji → `RED`;
  inaczej `PLAN (SPEC_REVIEW)`; brak testów → `PLAN (SPEC_REVIEW)` bez mavena; coverage i PIT nie są uruchamiane.
- `modes/spec-driven.md` — Planer: jedna reguła zakresu (wymagania bez testu `tc-agent-spec`, nic spoza spec;
  dopytanie w interactive o dane i niejasności) zastępuje akapity o `SPEC_REVIEW` i „COVERAGE_GAP… are context”.
  Recenzent: niepokryte linie bez cytującego scenariusza = `minor` „outside the spec”.
- Raport: przy niespełnionej bramce w spec-driven „outside the spec — a characterization run closes it”.
- Testy: spec-driven z czerwonym stale testem → `RED`; zielone → `PLAN (SPEC_REVIEW)`, tylko check testów.

**F17** — `tc_common.DEFAULT_PROTECTED = ["master", "main"]`, opis w schemacie profilu i `configuration.md`.
Przy okazji edycji: usunięcie powtórzeń, żeby bilans linii był ≤ 0.

### Etap 5 — Dokumentacja i anonimizacja (F18–F19)

**F18 — spójność dokumentacji**
- `README.md`: werdykt `ESCALATE`; RESEAL przed PLAN; brudny target = tylko characterization; spec-driven wymaga
  spec (orchestrator pyta); spec-driven tylko z wymagań; `flaky_repeat`; `main`.
- `docs/configuration.md`: jedno zdanie o rundach (runda = generate + review; nowa wersja planu nie daje dodatkowych);
  akapit Tooling bez opisu konkretnego repo; profil walidowany przy `start`; chronione `master`, `main`.
- `docs/TC-AGENT-PRZEWODNIK.md`: diagram (RESEAL → PLAN lub FINISH); CI = characterization bez interactive (plan);
  spec-driven bez łatania luk.
- `docs/MODEL-B-SPEC.md`: §3, §5, §6 wg D84–D100.
- `docs/MODEL-B2-PLAN.md`: kolejność ostatnich wpisów odchyleń.

**F19 — anonimizacja** (`docs/`, schematy, `tools/`)

Nazwy wewnętrznego projektu, jego modułów, repozytorium artefaktów i klas z przebiegów akceptacyjnych
zastąpione neutralnymi (`big-repo`, `rest-module`, `backend-module`, `plugin-module`, `CustomerDetailsService`,
`ConfirmationValidationService`, `FeeChargeService`, `DictionaryUtil`, …). Mapowanie stara → nowa nazwa leży
tylko lokalnie w `.test-agent/anonymize.txt` (gitignored), żeby ten plan sam ich nie publikował.

Kontrola końcowa: `grep` listy z `anonymize.txt` oraz przegląd pod kątem innych identyfikatorów (nazwy pakietów firmowych,
hosty, URL-e, e-maile) — zero trafień w repo.

**F25 — docstringi i komentarze w `scripts/`** (razem z F19, bo historie w docstringach niosą też nazwy do anonimizacji)
- docstring funkcji / klasy: krótki opis, co robi — bez historii („6500 plików, 6:42 min”), bez uzasadnień
  i bez odwołań do decyzji (historia jest w dzienniku, opis dla ludzi w `configuration.md`);
- docstring modułu: co robi skrypt + `Usage` + kody wyjścia (argparse pokazuje go w `--help`);
- komentarze: zostają tylko krótkie, tam gdzie kod sam nie mówi, co robi; narracje usunięte.
- Stan dziś: 118 docstringów funkcji (472 linie), docstringi modułów 257 linii, komentarze 200 linii.
  Szacunek po F25: ≈ −600 linii. Zero zmian w kodzie wykonywalnym — `git diff` F25 dotyka tylko docstringów
  i komentarzy (sprawdzane: AST plików przed i po bez docstringów musi być identyczne), dev-testy zielone.

### Etap 6 — Weryfikacja
1. Dev-testy zielone, w tym nowe testy regresji F1–F16 i F20–F23.
2. `tc_check_examples.py` OK.
3. Budżet linii (§5) spełniony.
4. Po stronie użytkownika: `tc_smoke_pipeline.py` z prawdziwym Mavenem i akceptacja §6; E38 decyduje o pozostawieniu etapu 3b.

---

## 5. Budżet (baseline 2026-10-10, `wc -l`)

| zakres | dziś | cel |
|---|---|---|
| prompty ról (orchestrator 79, planner 169, generator 121, reviewer 164) | 533 | ≤ 533 (po: 517) |
| `references/` (contracts 127, conventions 189, junit4 20, characterization 107, interactive 51, spec-driven 50) | 544 | ≤ 544 (po: 538) |
| `README.md` 104 + `docs/configuration.md` 200 | 304 | ≤ 304 |
| **razem pliki instrukcji pakietu** | **1381** | **≤ 1381 (po: 1359)** |
| `scripts/*.py` | 5265 | ≈ 4650 (F24 −40, F25 ≈ −600, poprawki F1–F23 bez dopisków) |
| `schemas/*.json` (etap 3b) | 1465 | ≈ 385 |

Rosnąć mogą tylko dev-testy (`tools/`) i dziennik decyzji (`docs/`).

## 6. Akceptacja (uruchamia użytkownik)

| # | scenariusz | oczekiwany wynik |
|---|---|---|
| E26 | ręczna zmiana `pom.xml` w trakcie przebiegu z `--commit` | `ESCALATED`, brak commita, `pom.xml` w raporcie |
| E27 | wymuszony `REPAIR_PLAN`, planer v2 zwraca `COMPLETE` | `ESCALATED`, brak commita |
| E28 | spec-driven bez spec | orchestrator pyta o ścieżkę, potem normalny przebieg |
| E29 | characterization, target z niezacommitowaną zmianą, testy zielone | `BLOCKED` przed mavenem |
| E30 | spec-driven, target z niezacommitowaną zmianą | przebieg działa |
| E31 | spec-driven, spec opisuje 3 z 5 gałęzi | testy tylko dla 3 wymagań; bramka NOT MET opisana jako „poza spec”; `DONE` |
| E32 | spec-driven + interactive, sprzeczne warunki (flaga vs lista) | jedno zamknięte pytanie; odpowiedź w `tc-agent-note` |
| E33 | spec-driven + interactive, wartość identyfikująca (numer rachunku brokerskiego) | pytanie o przykład; testy z podaną wartością |
| E34 | wymuszony `REPAIR_PLAN` | v2 = nowe scenariusze + `replaces`; generator realizuje całe v2, brak `SKIPPED` dla v2 |
| E35 | target `Klasa.metoda` z lambdą | niepokryte linie lambdy w checku coverage |
| E36 | `--commit` na `main` | nowy branch `tc-agent/<target>/<run-id>` |
| E37 | regresja E1–E25 | wyniki jak dotąd |
| E38 | **regresja jakości po etapie 3b:** te same targety (np. `AppointmentService`, `NotificationService`, `SimpleCalculatorService`) w characterization i spec-driven, przed i po 3b | ten sam outcome; liczba testów i zaślepek ±10%; bramki nie niższe; nie więcej `INVALID_ARTIFACT` ani rund; inaczej 3b cofnięty (`git revert`) |
| E39 | wymuszony `REPAIR_PLAN` po 3b | planer v2 planuje dokładnie linie / mutanty z plików checków; brak „nie widzę niepokrytych linii” |
| E40 | spec-driven bez interactive, sprzeczna spec, po 3b | `ESCALATED`; w raporcie `reason` z cytatem obu fragmentów |
| E41 | spec-driven, spec opisuje część klasy (bramka pokrycia klasy niespełniona) | PIT uruchomiony mimo to; mutant przeżywający w linii cytowanej przez scenariusz → `REPAIR_IMPLEMENTATION`; mutant poza spec → `minor` |

## 7. Poza zakresem / otwarte

- **Narzędzia ról (`tools` we frontmatterze)** — etap 8 planu B2, po stronie użytkownika. F1 zabezpiecza commit niezależnie od niego.
- **Automatyczny `mvn install`** zależności przy F7 — świadomie nie (zmienia `~/.m2`, decyzja człowieka).
- Historia gita przy publikacji — po stronie użytkownika.
- **Planer z mniejszą liczbą ograniczeń** (pomysł na przyszłość, 2026-10-18; dziś planer działa dobrze — bez zmian).
  Ograniczenia siedzą prawie wyłącznie w prompcie, więc ich zdjęcie to edycja `tc-planner.agent.md`; skrypty
  sprawdzające wynik zostają.

  | ograniczenie | gdzie | po zdjęciu | ryzyko | co dalej pilnuje |
  |---|---|---|---|---|
  | context pack, bez ad-hoc grep, ≤ 5 dodatkowych plików, potem `BLOCKED` (faza 2) | prompt | planer sam szuka builderów, danych, użyć — mniej `deferred` (największy potencjalny zysk) | czas, koszt, mniejsza powtarzalność | `tc_verify_refs` |
  | kolejność faz 0–6 | prompt | cel + kryteria zamiast procedury | małe | schemat planu, walidacja |
  | zakres z `reasons` derive-state | prompt | planer sam ocenia, czego brakuje | rozjazd zakresu; w spec-driven nie ruszać | recenzent, bramki |
  | `weak` → `deferred`, „never override the script” | prompt + skrypt | skrypt doradza, planer decyduje | słabiej udokumentowane scenariusze | recenzent (atrybucja, jakość) |
  | brak wiedzy z treningu o „typowych” obiektach, §A4 | prompt + `conventions.md` | **nie zdejmować** — test wynika z kodu, nie z wyobrażeń modelu | wysokie | — |

  Rozstrzygnięcie: drugi wariant promptu (najpierw luźniejsza faza 2), oba na tych samych targetach. Porównać:
  liczbę `deferred`, pokrycie i zabite mutanty po pierwszej rundzie, liczbę rund naprawczych, odrzucone refy,
  czas i koszt. Zmiana, gdy luźniejszy wariant ma mniej `deferred` przy tej samej liczbie rund i bez odrzuconych refów.

## 8. Odchylenia od planu

- 2026-10-10 (E0): baseline 460/460 asercji, `tc_check_examples` OK. Git w maszynie Coworku widzi drzewo Windows
  bez `autocrlf` (same CRLF); wszystkie komendy gita szły z `core.autocrlf=true`, autor = właściciel repo.
- E1 (F1): migawka pomija też `target/` — w repo bez `target/` w `.gitignore` sam maven zmieniałby ją w trakcie.
  F3: odmowa także dla nieistniejących `test_data_paths` z profilu. Stary test „dirty → DONE” zmieniony na D87.
- E2: F7 przez pole `dependencies_missing` w raporcie testów. F8 sprawdzone w źródle PIT (`DetectionStatus`):
  wykryte = KILLED, TIMED_OUT, NON_VIABLE, MEMORY_ERROR, RUN_ERROR, EQUIVALENT. F24: razem z `stale_classes`
  w `auto` zniknął komunikat „Another source in the module is stale”.
- E3: F12 rezerwuje miejsce także na SPEC. F13: refy w `data` sprawdzane, gdy mają kształt ścieżki.
  Reguła schematu `requirement` (F14) weszła z 3b.
- E3b: schematy = wersje robocze z `.test-agent/b3-schemas-draft/`; dispatch `REPAIR_PLAN` ma pole `gate_checks`;
  `tests.status` bez nieużywanych `ERROR` / `NOT_RUN`.
- E4: testy „generator v2 dostaje review” i „domyślnie tylko master” zmienione na D98 / D100.
- E5: F25 — skrypty 5359 → 4806 linii, AST bez docstringów identyczny. Wątki PIT: `-Dthreads=N` z linii komend
  (pitest.org quickstart: opcja `threads`, domyślnie 1). F19: lista z `anonymize.txt` — zero trafień w repo;
  stare nazwy zostają w historii gita.
- 2026-10-10 (po E6, pytanie użytkownika): w spec-driven recenzent pomijałby PIT, bo krok 4 wymaga spełnionej
  bramki pokrycia klasy, a spec opisuje zwykle tylko jej część. `modes/spec-driven.md`: mutacje zawsze przy zielonych
  testach; ocena jak dotąd (cytowane linie → Attribution, reszta `minor`). Akceptacja: E41.
- E6: 511/511 asercji; instrukcje 1381 → 1359 linii, skrypty 5265 → 4806, schematy 1465 → 385.
- 2026-10-18 (decyzja użytkownika): konfiguracja projektu zostaje w `.github/agents/tc-agent-project/` — jedyna
  ścieżka. Wycofane docelowe `.github/tc-agent/` z D69/E24 (`PROJECT_DIRS`, ostrzeżenie o dwóch katalogach, test `git mv`).
- 2026-10-18 (decyzja użytkownika): „slug” → `target` (po polsku „cel”): argument skryptów `<target>`, klucz
  `target_name` w `run.json`, derive-state, wyjściu orkiestratora i `run-report.md`, `Target.name` w kodzie.
- 2026-10-18 (decyzja użytkownika): plik projektu `test-data.md` → `test-data-examples.md` (nazwa mówi, co zawiera).
- 2026-10-18 (decyzja użytkownika): README pakietu kończy się sekcją „Files” — opis każdego pliku dla człowieka
  (żaden agent nie czyta README); budżet README rośnie świadomie. `architecture.svg` po angielsku.
- 2026-11-02 (przebieg użytkownika: characterization bez interactive, 10 z 16 scenariuszy jako zaślepki, bo brak
  przykładu poprawnego numeru rachunku odbiorcy — kaskada przez strażniki walidatora): §A4 źródło 4 obejmuje kod
  walidatora/klasyfikatora z repo (wartość zbudowana pod ten kod = `implementation`); suma kontrolna liczona kodem
  walidatora z repo, nigdy zgadywana; wartość oceniana przez mockowany walidator jest relacyjna; B5 mockuje
  wstrzykiwane walidatory i klasyfikatory, od których zależy strażnik; planer czyta je najpierw w escape hatch;
  wspólne pytanie dla scenariuszy z tą samą brakującą wartością, raport: `CONFIRM: <pytanie> — blocks: <metody>`.
