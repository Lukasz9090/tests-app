# tc-agent — Model B2: plan naprawczy (wersja odchudzona)

> **Status:** PLAN do akceptacji (2026-10-06). Zastępuje pierwszą wersję tego pliku z tego samego dnia — była za ciężka
> (5 nowych skryptów, 4 linty, 2 schematy, ~17 plików references). Nic nie jest jeszcze wdrożone.
> **Numeracja decyzji** kontynuuje `docs/MODEL-B-PLAN.md` (od D69).
> **Gałąź:** `model-b2`. **Punkt powrotu:** tag `model-b-final` (etap 0).
> **Założenie:** teraz wszystko leży pod `.github/agents/`, ale już w podziale na pakiet wspólny i konfigurację projektu.
> Przeniesienie konfiguracji do `<repo>/.github/tc-agent/` ma być jednym `git mv`, bez zmiany kodu.

---

## 0. Zasady

1. **Każda zmiana odpowiada na konkretny problem z przeglądu** — i to najprostszym mechanizmem, który go rozwiązuje.
2. **Nowy skrypt tylko po zmierzonym błędzie LLM**, nie „na zapas”. Najpierw rozszerzamy istniejący plik.
3. **Budżet instrukcji:** łączna liczba linii, które czyta rola (prompt + pliki, które każe przeczytać), nie rośnie
   względem baseline z etapu 0. Nowa reguła coś zastępuje albo przenosi.
4. **Rdzeń zostaje nietknięty:** derive-state, maszyna stanów w skryptach, metadane w Javadocu, reseal, trzy role
   z niezależnym recenzentem, bramki i atrybucja, evidence strength, dev-testy z fake mvn.
5. Każdy etap zostawia działający pipeline: dev-testy zielone, smoke na `tests-app` przechodzi.
6. **Bez wstecznej zgodności.** Agent jest w trakcie powstawania: zmiana nazwy, formatu albo ścieżki oznacza wycięcie
   starej wersji — bez aliasów, fallbacków i ostrzeżeń „deprecated”. Dane w `tests-app` (testy, profil) migrujemy
   jednorazowo w tym samym kroku, a nie przez kod, który czyta oba formaty.

---

## 1. Docelowy układ

```
.github/agents/
  tc-agent/                       WSPÓLNE (w przyszłości submodule)
    README.md
    tc-orchestrator.agent.md
    tc-planner.agent.md
    tc-generator.agent.md
    tc-reviewer.agent.md
    requirements.txt              (przeniesione z references/)
    references/
      contracts.md                artefakty, rundy, pack, skrypty, precedencja
      conventions.md              §A + §B; §A4 poprawiane w etapie 4
      junit4.md                   czytane tylko w repo na JUnit 4
      modes/
        characterization.md       ## Planner / ## Generator / ## Reviewer + przykład planu
        spec-driven.md            j.w.
        interactive.md            pytania, budżety, CONFIRM
    docs/configuration.md         opis katalogu projektu i kluczy profilu (dla ludzi)
    schemas/  scripts/  tools/    bez nowych plików

  tc-agent-project/               PROJEKTOWE — tymczasowo tutaj; docelowo <repo>/.github/tc-agent/
    profile.md                    bramki, freshness, maven, junit, max_rounds, protected_branches
    conventions.md                styl testów tego repo (nadpisania §B)
    test-data.md                  przykładowe dane biznesowe (proza, jak dziś)
```

| rzecz | wspólne | projektowe |
|---|---|---|
| prompty, references, schematy, skrypty, dev-testy | ✔ | |
| bramki, freshness, maven, junit, `max_rounds`, chronione branche | | `profile.md` |
| styl testów repo | | `conventions.md` (dalej czytane też: `copilot-instructions.md`, `*.instructions.md`, `AGENTS.md`, `instruction_paths`) |
| przykładowe dane | | `test-data.md` (+ `test_data_paths`, `--test-data`) |
| specyfikacje | | gdziekolwiek w repo, przez `--spec` |

**Jak skrypty znajdują katalog projektu:** stała w `tc_common.py`:

```python
PROJECT_DIRS = (".github/tc-agent", ".github/agents/tc-agent-project")   # pierwszy istniejący wygrywa
```

Druga pozycja to obecne położenie, pierwsza — docelowe (to nie jest zgodność wstecz, tylko przygotowanie przeniesienia).
Gdy istnieją oba katalogi, używany jest `.github/tc-agent`. Stare położenia profilu (`references/tc-project-profile.md`,
`tc-agent/tc-project-profile.md`) są wycinane bez fallbacku. Bez osobnego skryptu, bez narzędzia migracji.

---

## 2. Decyzje (D69–D83)

| # | obszar | ustalenie |
|---|---|---|
| D69 | Podział | Pakiet wspólny `.github/agents/tc-agent/`; konfiguracja projektu tymczasowo `.github/agents/tc-agent-project/`, docelowo `.github/tc-agent/`. Wyszukiwanie przez stałą `PROJECT_DIRS`. |
| D70 | Brudny target | „Dirty” = zmiana treści, nie końcówek linii (`git diff --quiet --ignore-cr-at-eol HEAD -- <plik>`). |
| D71 | Limit pętli | `max_rounds` (domyślnie 3) dla całego przebiegu; runda = GENERATE + REVIEW. **Usunięte:** `impl_cap`, `plan_cap`, automatyczny replan po wyczerpaniu napraw (D38) i `replan_cause: impl_cap_exhausted`. Przejście do nowego planu decyduje recenzent (ma już regułę „drugie powtórzenie → REPAIR_PLAN”). |
| D72 | References | 6 plików (§1). `state` dokłada do `dispatch` listę `references`: zawsze `contracts.md` + `conventions.md`, do tego `junit4.md` przy JUnit 4, `modes/<tryb>.md` i `modes/interactive.md` przy interactive. |
| D73 | Budżet instrukcji | Linie czytane przez rolę ≤ baseline. Historie incydentów i uzasadnienia wychodzą z promptów do dziennika decyzji. Każda reguła w jednym miejscu (dziś §A4 jest powtórzone w trzech promptach). |
| D74 | DATA EXAMPLES | `tc_build_context.py` dokłada do packa sekcję z liniami z CAŁEGO drzewa testów, które ustawiają pola używane przez target. Bez wnioskowania kształtu — robi to LLM. |
| D75 | §A4 | Wartość relacyjna pola, dla którego istnieje przykład (TEST DATA, DATA EXAMPLES, test, builder, `@Pattern`), dostaje kształt tego przykładu. Neutralny literał (`"KEY-1"`) tylko, gdy przykładu nie ma. Plus jawna kolejność źródeł (etap 4). |
| D76 | Spec-driven | Spec w packu; brak `DONE` na samych bramkach; metadane `tc-agent-spec`; rozbieżność spec↔kod obsłużona zwykłą rundą naprawy (test wyłączony z zachowanym ciałem). Zakres = tylko spec. |
| D77 | Interactive | **Rozstrzygnięte (2026-10-06):** planer jako subagent zadaje pytania na żywo i dostaje odpowiedzi (potwierdzone na obecnym rozwiązaniu). Protokół `NEEDS_INPUT` / `answer` NIE powstaje. Treść interactive przenosimy tylko do `modes/interactive.md`, a planer zachowuje narzędzie do pytań. |
| D78 | Narzędzia ról | `tools` we frontmatterze odkomentowane, zestaw per rola; generator bez terminala. |
| D79 | Dokumentacja | `MODEL-B-SPEC.md` = stan obecny; w `MODEL-B-PLAN.md` oznaczenia „zastąpione przez”; proza o mavenie → `tc-agent/docs/maven.md`. |
| D80 | Porządki | `_agent-fixes/` usunięty. |
| D81 | Nazwa trybu | `legacy` → **`characterization`** (nazwa mówi, co agent robi: zamraża obecne zachowanie; para z `spec-driven`: wyrocznią jest kod albo spec). `interactive` zostaje modyfikatorem, nie trzecim trybem: `--mode characterization \| spec-driven [--interactive]`. Słowo `legacy` znika z kodu, schematów, promptów i docs — bez aliasu. |
| D82 | Bez wstecznej zgodności | Wycinane: odczyt starych formatów metadanych w `tc_javadoc.py` (`@aiGenerated` / `@mode`, osobne `tc-agent: generated` i `tc-agent-interactive:`), stare ścieżki profilu, czytanie branchy z `AGENTS.md`, flagi `--impl-cap` / `--plan-cap`. Linia z nieznanym kluczem lub w starym formacie = zwykły `metadata_defect`. Testy w `tests-app` migrowane jednorazowo. |
| D83 | Jeden właściciel reguły | Każda reguła ma dokładnie jeden plik-właściciel (tabela w kroku 3.5). Prompt roli może odwołać się do niej numerem (`§A4`), ale nie powtarza treści; zawiera tylko to, co rola z regułą robi (planer cytuje dowód, generator pisze kod, recenzent sprawdza i decyduje). Uzasadnienia i historie incydentów nie trafiają do promptów. |

### 2.1 Świadomie odłożone (wracamy tylko z konkretnym powodem)

| pomysł | kiedy wrócić |
|---|---|
| `tc_check_data.py` (kontrola kształtu danych u recenzenta) | gdy E20/E21 pokażą `CUSTOMER-1` mimo DATA EXAMPLES. Wtedy wersja mini: regex na literały zastępcze w metodach z tej rundy, tryb warn, ~50 linii |
| osobny skrypt katalogu danych, wnioskowanie kształtu, JSON/SQL/Liquibase/OpenAPI | gdy przykłady z testów `.java` okażą się niewystarczające |
| schemat JSON dla `test-data.md`, automatyczne dopisywanie odpowiedzi | gdy ręczne wklejanie fragmentu z raportu będzie realnym kłopotem |
| sumy kontrolne (PESEL, NIP, IBAN) | gdy pojawi się błąd; do tego czasu jedno zdanie w §A4: „takie wartości kopiuj z przykładów, nie wymyślaj” |
| hash wymagań spec, auto-staleness testów spec, scenariusze `basis: code` | gdy spec-driven będzie używany regularnie |
| linty (budżet promptów, references, pakiet, docs) | budżet mierzymy raz `wc -l`; wystarczy jedna asercja w istniejącym dev-teście |

---

## 3. Etapy

### Etap 0 — Start (S)

1. Tag `model-b-final`, gałąź `model-b2`.
2. Dev-testy (`tools/tc_test_*.py`, `tc_check_examples.py`) zielone — baseline.
3. **Baseline instrukcji** (`wc -l`): dla każdej roli prompt + pliki, które każe czytać. Wynik wpisać do §5.
4. Usunąć `_agent-fixes/` (D80).

(Test „czy subagent umie pytać” niepotrzebny — potwierdzony na obecnym rozwiązaniu, D77.)

### Etap 1 — Higiena i limit rund (S) — D70, D71

**1.1 Końcówki linii.**
- `tc_git.is_dirty` → `git diff --quiet --ignore-cr-at-eol HEAD -- <plik>`;
- `tc_git.changed_lines` → `--ignore-cr-at-eol`;
- dev-test w `tc_test_derive_state.py`: zmiana tylko CRLF → nie dirty; zmiana treści → dirty; zmiana tylko w indeksie → dirty.

**1.2 Limit rund.**
- `start --max-rounds N` (domyślnie 3, profil `max_rounds`). Flagi `--impl-cap` / `--plan-cap` usunięte (D82) — także z promptu orchestratora, README i `run.json`.
- `state`: rundy = liczba `review-*.md` w przebiegu.

| warunek | `next_action` |
|---|---|
| `REPAIR_IMPLEMENTATION`, rundy < max | `GENERATE` |
| `REPAIR_PLAN`, rundy < max | `PLAN` (v+1) |
| rundy = max, brak ACCEPT | `FINISH` → `ESCALATED` „limit N rund”; testy zostają w drzewie, raport je wymienia |

- Usunąć z `tc_orchestrate.py` logikę D38 (replan po `impl_cap`) i jej gałęzie; z planera akapit o `impl_cap_exhausted`.
  Strażnik D41 w `finish` (czerwone testy → `RED`) zostaje.
- Raport: historia rund `1/3 … 3/3`.
- `tc_test_run_state.py`: każdy wiersz tabeli + „żadna sekwencja decyzji nie daje więcej niż 3 review”.

**1.3 Narzędzia ról** — przeniesione na koniec (etap 8); użytkownik jeszcze bada, jak Copilot traktuje `tools`.

**Kryterium:** E18, E19.

### Etap 2 — Katalog projektu (S) — D69

1. `PROJECT_DIRS` w `tc_common.py`; `profile()`, `freshness_days()`, `instruction_paths()`, `test_data_paths()`,
   `protected_branches()` czytają z katalogu projektu. Stare ścieżki profilu usunięte z `PROFILE_PATHS` (D82).
2. `protected_branches` jako klucz profilu (schemat profilu + `max_rounds`). Czytanie linii z `AGENTS.md` usunięte.
3. `conventions.md` projektu = pierwsze źródło w REPO CONVENTIONS; `test-data.md` projektu = automatycznie w TEST DATA.
4. Migracja `tests-app` ręcznie: utworzyć `.github/agents/tc-agent-project/`, przenieść JSON profilu do `profile.md`,
   linię branchy z `AGENTS.md` do `protected_branches`; usunąć `references/tc-project-profile.md`.
5. Opis kluczy profilu (w tym proza o mavenie) → `tc-agent/docs/configuration.md`. Profil = fence JSON + kilka linii.
6. Dev-testy (w istniejących `tc_test_build_context.py` / `tc_test_run_state.py`): oba katalogi, brak katalogu (domyślne bramki),
   `conventions.md` w packu, chronione branche z profilu, `git mv` do `.github/tc-agent` → ten sam wynik.

**Kryterium:** derive-state na `tests-app` identyczny jak przed etapem; E24.

### Etap 3 — References per tryb (M) — D72, D73. Refaktor bez zmiany zachowania

**3.1 Przeniesienia:**

| dziś | dokąd |
|---|---|
| `tc-contracts.md` | `contracts.md` (bez zmian treści) |
| `tc-test-conventions.md` | `conventions.md`; fragmenty tylko o JUnit 4 (A0, A2, A7, B2, B4, B5) → `junit4.md` |
| planer: freshness w interactive, stale/recharacterize, placeholdery stale, obsolete, `characterization: true`; generator: `tc-agent-characterizes`; recenzent: decyzja 4 | `modes/characterization.md` (sekcje per rola) |
| planer: 2 zdania o spec; recenzent: decyzja 5 | `modes/spec-driven.md` (rozbudowa w etapie 5) |
| planer: Round 1 / Round 2, `CONFIRM:` | `modes/interactive.md` |
| przykład planu z promptu planera | do pliku trybu |
| historie incydentów i uzasadnienia w promptach | dziennik decyzji w `docs/` |
| powtórzenia §A4 w trzech promptach | jedno miejsce: `conventions.md` §A4 |

Zostają w promptach ról (bo dotyczą jednej roli): naprawa planu (planer), runda naprawcza i `scope` (generator),
atrybucja i decyzje (recenzent), przykład raportu generacji i review.

**3.2 `dispatch.references`** w `tc_orchestrate.py` (~10 linii) + jedno zdanie w każdym prompcie:
„Przeczytaj po kolei pliki z `dispatch.references`; w pliku trybu twoja sekcja to `## <Rola>`”.

**3.3 Dev-test:** w `tc_test_run_state.py` — lista dla 4 kombinacji (characterization/spec-driven × interactive) i JUnit 4; każdy plik istnieje.

**3.4 Nazwa trybu i wycięcie zgodności (D81, D82)** — w tym samym kroku, bo pliki trybów i tak powstają od nowa:
- `legacy` → `characterization` w: `MODES` i `start` (`tc_orchestrate.py`), warunkach `mode == ...` (`tc_derive_state.py`,
  `tc_javadoc.py`, `tc_evidence_strength.py`, `tc_common.py`), enumach schematów planu i review, promptach ról,
  `contracts.md`, `conventions.md`, README, dev-testach (`tc_testkit.py`, `tc_test_*.py`) i komunikatach (`TARGET_TOO_FRESH` itd.);
- `tc_javadoc.py`: usunięte `AI_TAGS`, `OLD_FORMAT`, mapowanie `tc-agent` / `tc-agent-interactive` i gałęzie „older format”;
  jedyny poprawny zapis to `tc-agent-mode: <characterization|spec-driven>, interactive: <true|false>` (+ `characterizes`,
  `deferred`, `note`, a od etapu 5 `spec`). Dev-testy starych formatów w `tc_test_javadoc.py` → zamienione na test „stary format = defekt”;
- **migracja `tests-app`:** w `SimpleCalculatorServiceTest.java` (15 metod) usunąć linie `tc-agent: generated` i
  `tc-agent-interactive: true`, a `tc-agent-mode: legacy` zamienić na `tc-agent-mode: characterization, interactive: true`;
  osobny commit „migrate tc-agent metadata”, przed kolejnym przebiegiem;
- kontrola: `grep -rni legacy .github/agents` zwraca zero trafień.

**3.5 Deduplikacja promptów (D83).** Mapa właścicieli:

| reguła | dziś powtórzona w | właściciel |
|---|---|---|
| dane biznesowe (nie wymyślaj, wartości relacyjne, kształty obiektów) | conventions §A4; planer: prime directive, faza 4, Round 1, „Never ask…”, Never; generator: „cannot implement soundly”, „Data comes from the plan”, Never; recenzent: „misused placeholder” | `conventions.md` §A4 |
| metadane w Javadocu | conventions §A1; contracts §3 (ta sama tabela); generator (przykład + self-check); recenzent Stage 1 (wylicza linie) | `conventions.md` §A1; contracts §3 zostawia tylko ideę „kod jest bazą danych” |
| placeholdery | conventions §A2; contracts (niezmiennik); generator (tabela + self-check); recenzent Stage 1 | `conventions.md` §A2 |
| czas / Clock | conventions §A5; generator „Time”; self-check; recenzent | `conventions.md` §A5 |
| typ spoza packa ≠ powód do placeholdera | planer faza 2; generator; recenzent | `contracts.md` (jeden akapit o packu) |
| JUnit 4 | conventions (7 miejsc); bloki „Read first” w 3 promptach | `junit4.md` |
| nazwy i kolizje nazw | conventions §B1; planer faza 4 i 6; generator; recenzent | `conventions.md` §B1 (kolizje wyłapuje `tc_verify_refs.py`) |
| skrypt = czarna skrzynka | contracts §4; planer Never; recenzent Never (2×) | `contracts.md` §4 |
| nie kasuj pól, by przejść walidację | contracts §1; planer faza 6; planer Never | `contracts.md` §1 |
| tryb i interactive z `run.json` | contracts; orchestrator; wejście każdej roli | `contracts.md` + `dispatch` |
| „Read first, in this order” | 3 prompty | jedno zdanie o `dispatch.references` |

Do wycięcia w obrębie plików:
- recenzent: „bramki to poprzeczka” 3× → 1×; przykład `commit_summary` 2× → 1× (w JSON); wykład o `NOT_RUN` w decyzji 1 → „tylko wartości ze schematu”;
- generator: self-check (10 punktów, powtarza prompt) → 3 niezmienniki, których nie sprawdza nic innego;
- orchestrator: `WAIT` opisane 2× → 1×; „Never” powtarzające „Dispatch rules” → scalone; zarezerwowany `tdd` → usunięty;
- wszystkie role: narracje z incydentów („'Repaired one test' is wrong…”, „a repair here would chase…”, dlaczego kontener to Markdown) → dziennik decyzji;
- planer: przykład planu (~100 linii) przycięty do jednego scenariusza, jednego `replaces` i jednego `deferred`, przeniesiony do pliku trybu.

Docelowe długości promptów ról (kryterium etapu):

| plik | dziś | cel |
|---|---|---|
| `tc-planner.agent.md` | 453 | ≤ 250 |
| `tc-generator.agent.md` | 223 | ≤ 120 |
| `tc-reviewer.agent.md` | 247 | ≤ 160 |
| `tc-orchestrator.agent.md` | 118 | ≤ 75 |

Kontrola właścicieli: frazy-wyróżniki reguł (np. „relational”, „AI deferred:”, „black box”) występują tylko w pliku-właścicielu — sprawdzane `grep` w dev-teście.

**Kryterium:** dev-testy zielone; E1–E3 dają ten sam outcome co przed refaktorem; `derive-state` na `tests-app` po migracji nie zgłasza `metadata_defects`; długości promptów w celach z 3.5; budżet instrukcji ≤ baseline
(cel dla planera w characterization bez interactive: −30%).

### Etap 4 — Dane biznesowe (S/M) — D74, D75

**4.1 Sekcja DATA EXAMPLES w `tc_build_context.py` (~80 linii):**
- nazwy pól: parametry publicznych metod targetu + pola i komponenty rekordów klas zależności poziomu 1 o typach
  „wartościowych” (`String`, liczby, `UUID`, `BigDecimal`, enumy pomijamy — są już w packu);
- jeden `git grep -n -w` po wszystkich test roots (i `src/test/resources`) na alternatywę tych nazw;
- zostają linie z literałem; odrzucone linie asercji (`assert`, `isEqualTo`, `verify`);
- do 3 linii na nazwę, różne wartości, najlepiej z różnych plików; limit ~6k znaków;
- miejsce w packu: po TEST DATA, przed REPO CONVENTIONS.

```
## DATA EXAMPLES (lines from existing tests that set the fields this target uses)
customerId
  src/test/java/com/acme/customer/CustomerServiceTest.java:41   String customerId = "123456789";
  src/test/java/com/acme/order/OrderControllerTest.java:88      .customerId("987654321")
customerEmail
  src/test/java/com/testsapp/service/AppointmentServiceTest.java:57   "jan.kowalski@example.pl",
```

**4.2 `conventions.md` §A4** — poprawka i kolejność źródeł (zastępuje dzisiejsze akapity o danych w planerze i generatorze):
1. TEST DATA (pliki wskazane przez człowieka, w tym `test-data.md` projektu);
2. `known_test_data` z tego przebiegu;
3. DATA EXAMPLES i testy w packu;
4. buildery, fixture'y, seedery, ograniczenia walidacji (`@Pattern`, `@Size`) z packa;
5. pytanie do człowieka — tylko w interactive;
6. neutralny literał — tylko gdy 1–5 nic nie dają.

Plus: każda encja i każde pole własna wartość tego kształtu; identyfikatory z sumą kontrolną (PESEL, NIP, IBAN)
kopiuj z przykładów, nie wymyślaj. Cytowany przykład = dowód `existing_test`.

**4.3 Dev-test** (`tc_test_build_context.py`): nazwa użyta tylko w innej klasie testowej trafia do sekcji;
asercje odrzucone; limit działa; brak nazw → brak sekcji.

**Kryterium:** E20, E21. **Wynik E20/E21 decyduje o `tc_check_data` (§2.1).**

### Etap 5 — Spec-driven oparty na specyfikacji (M) — D76

1. **Pack:** sekcja SPEC z treścią pliku z `run.json` (budżet ~30k znaków, z notatką przy obcięciu), przed TARGET.
2. **derive-state:** w `spec-driven` wynik „bramki spełnione → `DONE`” zamienia się na `PLAN` z powodem `SPEC_REVIEW`.
   Planer porównuje spec z istniejącymi testami i może zwrócić `COMPLETE` (istniejący stan sukcesu). Koszt: jedno wywołanie planera.
3. **Metadane:** nowa linia `tc-agent-spec: <plik>#<id wymagania albo nagłówek>` (parser `tc_javadoc` + dev-test).
   Bez hasha i bez auto-staleness — ten sam kompromis co dziś. derive-state wypisuje istniejące odwołania
   `tc-agent-spec`, żeby planer wiedział, co jest już pokryte.
4. **Zakres:** tylko wymagania ze spec. Luki w kodzie łata osobny przebieg `characterization` (raport o tym mówi).
5. **Rozbieżność spec↔kod — zwykła runda naprawy, bez nowych stanów:**
   - recenzent: asercja testu napisanego w tym przebiegu nie przechodzi, setup jest poprawny, oczekiwanie zgodne ze spec →
     finding `spec_mismatch` (cytat spec, oczekiwane, faktyczne) i `REPAIR_IMPLEMENTATION` z `scope: "disable"`;
   - generator: dodaje `@Disabled("AI spec-mismatch: <krótko>")` i `tc-agent-note: spec mismatch: <spec / kod>`, **ciało zostaje**;
   - recenzent w następnej rundzie: taki test jest poprawny (wyjątek w Stage 1 od „IMPLEMENTED nie jest disabled”) → `ACCEPT_PARTIAL`;
   - `finish`: sekcja „Rozbieżności spec ↔ kod” z findingów `spec_mismatch`;
   - `NEEDS_TRIAGE` zostaje tylko dla czerwonych testów spoza tego przebiegu.
6. **Schematy:** `scope` + `"disable"`, typ findingu `spec_mismatch`. Treść ról → `modes/spec-driven.md`.

**Kryterium:** E22, E23.

### Etap 6 — Interactive — USUNIĘTY (D77)

Planer już dziś pyta na żywo, więc nie ma czego budować. Jedyna praca przy interactive dzieje się w innych etapach:
- etap 1.3: planer zachowuje narzędzie do pytań po odkomentowaniu `tools`;
- etap 3: Round 1 / Round 2 i `CONFIRM:` przechodzą z promptu planera do `modes/interactive.md` — bez zmiany treści;
- etap 5: pytania o niejednoznaczne wymagania spec dopisane do `modes/interactive.md` (kilka linii).

Regresja: E25.

### Etap 7 — Dokumentacja i akceptacja (S + u Ciebie) — D79

1. `docs/MODEL-B-SPEC.md` → stan obecny: układ z §1, metadane (jedna linia `tc-agent-mode`, `tc-agent-spec`), tryby `characterization` / `spec-driven` + `interactive`, limit rund, dane. Bez opisów starych formatów.
2. `docs/MODEL-B-PLAN.md` → oznaczenia „zastąpione przez”: D28→D34, D38/D41→D71, D43→D45, D55→D63; §6.1, §6.4, §10.5 jako historyczne.
3. `tc-agent/README.md`: katalog projektu, `--max-rounds`, spec-driven, DATA EXAMPLES.
4. Ten plik: §6 „Odchylenia” po wdrożeniu.

**Akceptacja** — regresja E1–E17 (MODEL-B-PLAN §11; E16/E17 z branchami z `profile.md`) oraz:

| # | scenariusz | oczekiwany wynik |
|---|---|---|
| E18 | bramka 0.99 (wymuszone naprawy) | najwyżej 3 review, `ESCALATED` „limit 3 rund”, historia 1/3…3/3 |
| E19 | target różni się tylko CRLF | nie `BLOCKED` |
| E20 | `customerId` (9 cyfr) tylko w testach INNEJ klasy | nowe testy używają 9 cyfr, różne wartości dla różnych encji; brak `CUSTOMER-1`; zero pytań |
| E21 | klucz relacyjny z przykładem / bez przykładu | kształt przykładu / `KEY-1` |
| E22 | spec-driven na klasie z pełnymi testami charakteryzacyjnymi | `PLAN (SPEC_REVIEW)`, nie `DONE`; testy z `tc-agent-spec` albo `COMPLETE` z wyjaśnieniem |
| E23 | spec-driven z celową rozbieżnością w kodzie | test wyłączony z zachowanym ciałem, `DONE_PARTIAL`, sekcja rozbieżności w raporcie |
| E24 | `git mv .github/agents/tc-agent-project .github/tc-agent` | identyczny wynik `start` |
| E25 | characterization + interactive po refaktorze (etapy 1.3 i 3) | planer nadal pyta o dane i zamrożenie; odpowiedzi w `context.test_data` / `tc-agent-note` jak dziś |

---

### Etap 8 — Narzędzia ról (ostatni) — D78

Spisać aktualne nazwy narzędzi z VS Code i wpisać `tools` per rola:

| rola | narzędzia |
|---|---|
| orchestrator | subagent, terminal |
| planner | odczyt, terminal (skrypty), tworzenie pliku, **pytania do człowieka** (to samo narzędzie, które działa dziś — nie może zniknąć przy odkomentowaniu `tools`) |
| generator | odczyt, wyszukiwanie, problemy kompilacji, tworzenie/edycja plików — **bez terminala** |
| reviewer | odczyt, wyszukiwanie, terminal, tworzenie pliku |

**Kryterium:** w UI Copilota generator nie ma terminala; planer w interactive nadal zadaje pytania (E25).

---

## 4. Kolejność

```
E0 ─► E1 ─► E2 ─► E3 ─┬─► E4 ─┬─► E7 ─► E8
                      └─► E5 ─┘
```

E3 przed E4–E5, żeby nowa treść trafiała od razu do właściwych plików, a nie rozpychała obecnych promptów.
E4 i E5 są niezależne — kolejność wg pilności. (Etap 6 usunięty — D77.)

---

## 5. Bilans i metryki

| | pierwsza wersja planu | ta wersja |
|---|---|---|
| nowe skrypty | 5 | 0 (zmiany w istniejących) |
| nowe linty / narzędzia | 4 + 5 plików dev-testów | 0 (rozszerzone istniejące dev-testy) |
| nowe schematy | 2 | 0 (kilka pól w istniejących) |
| pliki references | ~17 + 5 szablonów | 6 |
| nowe komendy / stany | `answer`, `mark-mismatch`, `ASK`, `MARK_MISMATCH` | 0 |
| nowe linie metadanych | 2 | 1 (`tc-agent-spec`) |
| logika pętli | nowa tabela + replan | mniej kodu niż dziś |
| decyzje | 23 | 15 |

| metryka | baseline (etap 0) | cel |
|---|---|---|
| linie instrukcji czytane przez planera (characterization, bez interactive) | 806 (453 prompt + 147 contracts + 206 conventions) | −30% (≤ 565) |
| linie instrukcji czytane przez generator / recenzenta | 576 / 600 | ≤ baseline |
| linie instrukcji czytane przez orchestrator | 265 | ≤ baseline |
| linie promptów ról (4 pliki) | 1041 | ≤ 605 (−40%) |
| maks. wywołań LLM w przebiegu | 3 P + 6 G + 6 R | ≤ 3 P + 3 G + 3 R |
| `CUSTOMER-1`-podobne literały w E20 | do zmierzenia | 0 |
| spec-driven kończący `DONE` bez czytania spec | możliwe | niemożliwe (E22) |

---

## 6. Po E7 — czego ten plan celowo nie obejmuje

Po E7 wymagania wyjściowe są spełnione w wersji 1: repo-agnostyczny agent (Java / Spring Boot / Maven), wytyczne
per repo w md, tryby characterization i spec-driven z interactive, limit 3 rund, dane biznesowe brane z istniejących testów.
Poniższe punkty są następne w kolejce — każdy jako osobny plan.

| # | temat | co zostaje do zrobienia | dlaczego nie teraz |
|---|---|---|---|
| P1 | **Dystrybucja pakietu** | wydzielenie `.github/agents/tc-agent/` do osobnego repo; submodule albo subtree w repo docelowych; wersjonowanie (tag pakietu w `run-report.md`); procedura aktualizacji; `git mv .github/agents/tc-agent-project .github/tc-agent` w każdym repo | struktura jest gotowa po E2, ale zasady dystrybucji warto ustalić dopiero na stabilnym pakiecie |
| P2 | **Walidacja na prawdziwych projektach** | przebiegi E1–E25 na 1–2 realnych repo (np. `ces`: wielomodułowy, JUnit 4, generatory, długi build); zebranie metryk z §5; poprawki jako odchylenia | `tests-app` jest za mały, by pokazać problemy skali i danych biznesowych |
| P3 | **Rodzaje testów Spring** | decyzja, czy agent ma pisać także `@WebMvcTest` (kontrolery), `@DataJpaTest` (repozytoria), testy integracyjne; jeśli tak — osobny plik `modes/` albo `references/spring-slices.md` i reguły wyboru rodzaju testu | dziś zakres to test jednostkowy jednej klasy z zamockowanymi repozytoriami (§B5); poszerzenie zmienia derive-state, bramki i koszt buildu |
| P4 | **Powroty z §2.1** | `tc_check_data` (mini), katalog danych z JSON/SQL, hash wymagań spec i auto-staleness, `basis: code` w spec-driven | tylko jeśli pomiary po E4/E5 i P2 pokażą, że wersja podstawowa nie wystarcza |

## 7. Ryzyka i odchylenia

| # | ryzyko | mitygacja |
|---|---|---|
| R10 | Po przeniesieniu treści do references model gubi reguły | §A zostaje w zawsze czytanym `conventions.md`; regresja E1–E3 przed nowymi funkcjami |
| R11 | Subagent nie przeczyta wszystkich plików z listy | lista krótka (2–5 plików); Stage 1 recenzenta sprawdza efekty |
| R12 | DATA EXAMPLES łapie przypadkowe nazwy (`id`, `name`) | tylko nazwy z targetu i jego DTO; limit 3 linii na nazwę; gołe `id` pomijane |
| R13 | Limit 3 rund zwiększy liczbę `ESCALATED` | raport mówi, co zostało; `max_rounds` w profilu dla trudnych modułów |
| R14 | Spec-driven kosztuje zawsze jedno wywołanie planera | świadomie — inaczej spec nie byłby czytany |

**Odchylenia od planu:**
- 2026-10-06 (E0): baseline — dev-testy 401/401 zielone (`build_context` 25, `check_scripts` 112, `derive_state` 64, `javadoc` 73, `run_state` 127), `tc_check_examples` OK (wymaga `jsonschema>=4`; 3.2 nie ma `Draft202012Validator`). Tag `model-b-final`, gałąź `model-b2` od `refactor-new-context`.
- 2026-10-06 (E0): „31 brudnych plików” z przeglądu to artefakt środowiska — repo nie ustawia `core.autocrlf`, a na Windows git (autocrlf=true) widzi drzewo czyste. D70 zostaje jako zabezpieczenie dla repo/CI bez autocrlf, ale nie było realnej blokady. Przy okazji: `src/test/` (w tym `SimpleCalculatorServiceTest.java`) jest nieśledzony przez git.
- 2026-10-06 (E0): `_agent-fixes/` usunięty (44 pliki).
- 2026-10-06 (E1.1): `tc_git.is_dirty` = `git diff --quiet --ignore-cr-at-eol HEAD` + nieśledzony plik; `changed_lines` z `--ignore-cr-at-eol`. Dev-testy: CRLF-only nie jest dirty, zmiana w indeksie i nowy plik są.
- 2026-10-06 (E1.2): `max_rounds` (run.json, profil, `--max-rounds`); `impl_cap`, `plan_cap`, `replan_cause` i replan po wyczerpaniu napraw usunięte ze skryptów, promptów, README, contracts i schematów. Raport: `rounds (k of N)`. Usunięty też test „czerwone testy nie przeplanowują” — reguła zniknęła razem z automatycznym replanem; czerwony suite po 3 rundach kończy `ESCALATED`, a strażnik `RED` w `finish` zostaje. Dev-testy 408/408 (`run_state` 131, w tym „żadna sekwencja decyzji nie daje 4. review”).
- 2026-10-06 (E1.3): przeniesione jako etap 8 (ostatni) — użytkownik bada zachowanie `tools` w Copilocie; listy zostają zakomentowane.
- 2026-10-06 (E2): `PROJECT_DIRS` + `project_dir()` / `project_file()` w `tc_common`; profil, `protected_branches` (nowy klucz, bez `AGENTS.md`), `conventions.md` (pierwsze źródło REPO CONVENTIONS) i `test-data.md` (zawsze w TEST DATA) z katalogu projektu. Stare `references/tc-project-profile.md` usunięte bez fallbacku. Odchylenie: opis kluczy trafił do `tc-agent/docs/configuration.md` (cały profil, nie tylko maven), a w `tests-app` katalog projektu ma `profile.md` + `README.md` — `conventions.md` i `test-data.md` nie powstały, bo puste pliki tylko dodawałyby szum do packa (opcjonalne, wykrywane gdy są). `tc_check_examples` waliduje profil projektu. Dev-testy 416/416.
- 2026-10-06 (E3): `references/` = `contracts.md`, `conventions.md`, `junit4.md`, `modes/characterization.md`, `modes/spec-driven.md`, `modes/interactive.md` (stare `tc-contracts.md` / `tc-test-conventions.md` usunięte, `tc-requirements.txt` → `tc-agent/requirements.txt`). `state` dokłada `dispatch.references`; `modes/interactive.md` dostaje tylko planer. Prompty ról: 1041 → 527 linii (orchestrator 79, planner 166, generator 120, reviewer 162 — orchestrator i reviewer o kilka linii ponad cel z 3.5, łączny cel ≤ 605 spełniony). Instrukcje czytane w przebiegu characterization bez interactive: planner 806 → 550 (−32%), generator 576 → 504, reviewer 600 → 546, orchestrator 265 → 200. §A3 (semantyka trybu) przeszła do plików trybów; przykład planu do `modes/characterization.md`. `legacy` → `characterization` w kodzie, schematach, promptach i docs; jedyne wystąpienie `legacy` to celowy test, że stara nazwa jest odrzucana. Odchylenie od D82: zapis `@aiGenerated` nie jest już rozpoznawany wcale (metoda czyta się jak ludzka) zamiast zgłaszać defekt — rozpoznawanie byłoby właśnie kodem zgodności. `SimpleCalculatorServiceTest.java` zmigrowany (15 metod, 0 defektów), ale plik jest nieśledzony przez git, więc zmiana jest tylko w drzewie roboczym. Nowe dev-testy: `dispatch.references` dla kombinacji trybów i JUnit 4, „jeden właściciel reguły” (frazy-wyróżniki tylko w pliku-właścicielu). Dev-testy 434/434.
- 2026-10-06: planer jako subagent zadaje pytania na żywo (potwierdzone przez użytkownika na obecnym rozwiązaniu) → etap 6 usunięty, D77 rozstrzygnięte.
