# Test Agent — PoC (copilot-cli)

Trzy agenty z architektury: **Test Planner** (plan z evidence), **Test Generator**
(kod testów) i **Test Reviewer** (uruchomienie, metryki, decyzja). Orchestrator
jest kolejnym krokiem — na razie agenty uruchamia się ręcznie, po kolei.

## Instalacja w repozytorium docelowym

1. Skopiuj katalog `.github/agents/` do roota repo Java (Maven).
2. Dodaj do `.gitignore` JEDNĄ linię (całe runtime agentów):
   ```
   .test-agent/
   ```
3. Bootstrap środowiska skryptów (jednorazowo, Windows/Linux/macOS):
   ```
   python .github/agents/common/scripts/setup.py
   ```
   (tworzy venv w `.test-agent/.venv` i instaluje jsonschema)

## Struktura

```
.github/agents/
├── test-planner.agent.md
├── test-planner/
│   ├── scripts/  build_context.py, compute_confidence.py, verify_refs.py
│   └── schemas/  test-plan.schema.json
├── test-generator.agent.md
├── test-generator/
│   └── schemas/  generation-report.schema.json
├── test-reviewer.agent.md
├── test-reviewer/
│   ├── scripts/  _common.py, run_tests.py, coverage.py, mutation.py
│   └── schemas/  review.schema.json
└── common/
    └── scripts/  md_payload.py, validate_plan.py, setup.py   # współdzielone
.test-agent/                    # RUNTIME (gitignore):
├── plans/<Target>/             #   plan-vN.md, generation-report-vN.md, review-vN-rM.md
├── context/<Target>/           #   context-pack.md
├── checks/<Target>/            #   tests-rM.md, coverage-rM.md, mutation-rM.md, jacoco.exec, pit-history.bin
├── project-profile.md          #   progi i wersje narzędzi (opcjonalny)
└── .venv/
```

## Pipeline (deterministyczna kanapka)

```
PLANNER:   build_context.py → test-planner → verify_refs.py + validate_plan.py
GENERATOR: plan + pack (+ review) → test-generator → testy + generation-report-vN.md
REVIEWER:  run_tests.py → coverage.py → mutation.py → test-reviewer → review-vN-rM.md
```

## Uruchomienie

```bash
copilot --agent=test-planner   -p "target: src/main/java/com/acme/OrderService.java, mode: legacy"
copilot --agent=test-generator -p "target: OrderService"
copilot --agent=test-reviewer  -p "target: OrderService"
```

albo interaktywnie: `copilot` → `/agent` → wybór agenta.

Tryby Plannera: `legacy` (default, characterization), `spec-driven` (+ ścieżka
spec), `interactive` (agent zadaje pytania przy brakach evidence).
Wynik Plannera: `.test-agent/plans/<Target>/plan-v<N>.md` — katalog per target,
plik per wersja; repair podnosi numer wersji, plików nie edytujemy.

Generator nie uruchamia testów (to rola Reviewera); mockuje klasy `*Repository`
jako granicę bazy; scenariusz niedeterministyczny bez seamu (np. brak `Clock`)
oznacza BLOCKED z sugestią zmiany kodu. Gdy istnieje review, Generator
implementuje scenariusze `NEW`/`MODIFIED` **oraz** każde TC wymienione
w `feedback.implementation`, niezależnie od flagi `change`.

## Reviewer — checki i decyzje

Trzy skrypty, wołane przez agenta etapowo (drogie dopiero po tanich):

```bash
<venv-python> .github/agents/test-reviewer/scripts/run_tests.py <Target> --repo . --repeat 2
<venv-python> .github/agents/test-reviewer/scripts/coverage.py  <Target> --repo .
<venv-python> .github/agents/test-reviewer/scripts/mutation.py  <Target> --repo .
```

- `run_tests.py` — **jedyny krok, który buduje projekt**; zawsze dopina agenta
  JaCoCo, więc `coverage.py` raportuje z gotowego `jacoco.exec` bez ponownego
  uruchamiania testów. Rozróżnia błąd kompilacji od oblanego testu oraz błąd
  **w asercji** od błędu **przed asercją** (`failure_phase`).
- `coverage.py` — cel `jacoco:report` wołany bezpośrednio (bez kompilacji);
  zakres = metoda targetu, jeśli plan ją wskazuje, inaczej klasa; zwraca
  konkretne niepokryte linie, nie sam procent.
- `mutation.py` — PIT z `targetClasses`/`targetTests` i plikiem historii
  (kolejne iteracje pomijają niezmienione mutanty); zwraca survivorów
  z linią i mutatorem.

Exit code'y są rozłączne: `0` = bramka spełniona, `1` = defekt jakościowy
(repair), `2` = check się nie wykonał → `BLOCKED`, nigdy „passed".

Decyzje Reviewera: `ACCEPT` | `ACCEPT_PARTIAL` (są scenariusze BLOCKED, których
regeneracja nie naprawi) | `REPAIR_IMPLEMENTATION` | `REPAIR_PLAN` |
`NEEDS_TRIAGE` (test oblał w asercji w trybie spec-driven/interactive — kod może
być zabugowany, decyduje człowiek) | `BLOCKED`.

## Weryfikacja ręczna (niezależnie od agenta)

`<venv-python>` to interpreter z venv utworzonego przez setup.py:
- Windows: `.test-agent\.venv\Scripts\python.exe`
- Linux/macOS: `.test-agent/.venv/bin/python`

```bash
<venv-python> .github/agents/test-planner/scripts/compute_confidence.py .test-agent/plans/<Target>/plan-v<N>.md --write
<venv-python> .github/agents/test-planner/scripts/verify_refs.py .test-agent/plans/<Target>/plan-v<N>.md --repo .
<venv-python> .github/agents/common/scripts/validate_plan.py .test-agent/plans/<Target>/plan-v<N>.md .github/agents/test-planner/schemas/test-plan.schema.json
<venv-python> .github/agents/common/scripts/validate_plan.py .test-agent/plans/<Target>/generation-report-v<N>.md .github/agents/test-generator/schemas/generation-report.schema.json
<venv-python> .github/agents/common/scripts/validate_plan.py .test-agent/plans/<Target>/review-v<N>-r<M>.md .github/agents/test-reviewer/schemas/review.schema.json
```

Exit code walidatora: 0 = artefakt poprawny, 1 = INVALID_ARTIFACT.

## Jak ocenić, czy Planner działa dobrze (checklista PoC)

- [ ] każdy `ref` w evidence **istnieje naprawdę** w repo (klasa, test, linia)
  — to najważniejszy test; zmyślony ref = porażka prime directive
- [ ] dane scenariuszy wskazują na **istniejące buildery/fixtures**, a nie
  wymyślone wartości typu `new Customer("John", ...)`
- [ ] scenariusze pokrywają gałęzie widoczne w kodzie (nie tylko happy path)
- [ ] scenariusze **nie duplikują** istniejących testów (te są w
  `context.existing_tests`)
- [ ] wątpliwe przypadki wylądowały w `deferred` z sensownym pytaniem,
  a nie w `scenarios` z naciąganym evidence
- [ ] confidence odpowiada intuicji (test+builder wysoko, sam enum nisko)
- [ ] status zgodny z zawartością (READY_PARTIAL gdy jest deferred itd.)

Uruchom na 2–3 różnych klasach (prosta / z zależnościami / legacy god class)
i na minimum 2 różnych repo — to weryfikuje repo-agnostyczność.

## Jak ocenić, czy Reviewer działa dobrze

- [ ] każdy `location` w findings da się znaleźć w wyjściu skryptu albo w teście
- [ ] finding z `attributed_to: plan` ma `checked_scenarios` — widać, które
  scenariusze sprawdzono, zanim uznano gałąź za lukę planu
- [ ] feedback jest adresowany liniowo („survivor w linii 147, mutator X"),
  a nie ogólnikowy („popraw asercje")
- [ ] PIT nie uruchomił się, gdy testy były czerwone albo coverage poniżej progu
- [ ] scenariusz BLOCKED z generation-report nie wygenerował pętli repair
- [ ] brak `pitest-junit5-plugin` daje `SKIPPED_UNAVAILABLE` + `BLOCKED`,
  nigdy „mutation passed"

## Kalibracja

- Wagi evidence: `WEIGHTS` w `compute_confidence.py` — jedno miejsce, jawne.
- Progi i wersje narzędzi: `.test-agent/project-profile.md` — kontener markdown
  z jednym blokiem ```json (polityka org blokuje `.json` i `.yaml`). Blok musi
  być na poziomie dokumentu, nie wcięty pod punktem listy — parser szuka fence'a
  od początku linii:

```json
{
  "schema_version": 1,
  "confidence": { "threshold": 0.75 },
  "quality_gates": {
    "branch_coverage_target_scope": 0.80,
    "mutation_score_target_scope": 0.70
  },
  "tooling": { "jacoco_version": "0.8.15", "pit_version": "1.25.9" }
}
```

Brak pliku = defaulty agentów. Skrypty Reviewera przyjmują też `--gate`,
`--jacoco-version`, `--pit-version` i `--module` jako nadpisanie ad hoc.

Wersja pluginu rozstrzygana jest w kolejności: **flaga CLI → project-profile.md →
wersja z poma → default agenta**. Musi być na tyle nowa, żeby przeczytać class
files Twojego JDK — inaczej `jacoco:report` kończy się `Unsupported class file
major version NN` (NN−44 = wersja Javy; np. 70 = Java 26, wymaga JaCoCo ≥ 0.8.15).

## Znane uproszczenia PoC (świadome)

- Brak czynnika świeżości w confidence (wejdzie z detekcją STALE, D9).
- Brak Project Knowledge — każdy run robi discovery od zera.
- `validate_repository` wykonywane przez agenta wg instrukcji, nie jako
  osobny skrypt (do wydzielenia w V1).
- Zakres metody w JaCoCo wyznaczany heurystycznie (od linii metody do linii
  następnej) — JaCoCo nie podaje zakresów metod wprost.
- Brak Orchestratora: kolejność agentów i limity iteracji pilnuje człowiek.