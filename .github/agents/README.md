# Test Planner — PoC (copilot-cli)

Pierwszy agent z architektury: **Test Planner**. Generuje `test-plan.md`
z evidence-backed scenariuszami. Nie pisze kodu testów.

## Zawartość

```text
.github/agents/test-planner.agent.md    # definicja agenta (copilot-cli)
.test-agent/schemas/test-plan.schema.json   # kontrakt planu (D12)
.github/agents/test-planner/scripts/compute_confidence.py   # deterministyczne confidence (D4)
.github/agents/test-planner/scripts/validate_plan.py        # twarda walidacja schematu (D12)
```

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
├── test-planner.agent.md            # agent Plannera
├── test-planner/
│   ├── scripts/  build_context.py, compute_confidence.py, verify_refs.py
│   └── schemas/  test-plan.schema.json
├── test-generator.agent.md          # agent Generatora
├── test-generator/
│   └── schemas/  generation-report.schema.json
└── common/
    └── scripts/  md_payload.py, validate_plan.py, setup.py   # współdzielone
.test-agent/                         # RUNTIME (gitignore): plans/, context/, .venv/
```

## Uruchomienie

W repo docelowym:

```bash
copilot --agent=test-planner -p "target: src/main/java/com/acme/OrderService.java, mode: legacy"
```

albo interaktywnie: `copilot` → `/agent` → `test-planner` → podaj target i mode.

Tryby: `legacy` (default, characterization), `spec-driven` (+ ścieżka spec),
`interactive` (agent zadaje pytania przy brakach evidence).

Wynik: `.test-agent/plans/<Target>/plan-v<N>.md` + podsumowanie w terminalu.
Katalog per target (np. `OrderService.createOrder/`), wersja per plik;
kolejne targety dostają własne katalogi, repair podnosi numer wersji.

## Pipeline (deterministyczna kanapka)

```
PLANNER:   build_context.py → test-planner → verify_refs.py + validate_plan.py
GENERATOR: plan + pack      → test-generator → testy + generation-report-vN.md
REVIEWER:  (następny krok PoC — compile/run/JaCoCo/PIT + review semantyczny)
```

Generator: `copilot --agent=test-generator -p "target: AppointmentService"`.
Nie uruchamia testów (to rola Reviewera); mockuje klasy *Repository jako
granicę bazy; scenariusze niedeterministyczne bez seamu (np. brak Clock)
oznacza BLOCKED z sugestią zmiany kodu w sekcji suggestions raportu.
Walidacja raportu: `.github/agents/common/scripts/validate_plan.py <report.md> .github/agents/test-generator/schemas/generation-report.schema.json`

- `build_context.py <Klasa[.metoda]> --repo .` — deterministyczny wycinek
  (target, deps L1 pełne / L2 sygnatury, testy, buildery, enumy) z twardym
  budżetem znaków; wynik: `.test-agent/context/<Target>/context-pack.md`
- `verify_refs.py <plan> --repo .` — mechanicznie sprawdza KAŻDY ref
  evidence w repo; zmyślony ref = INVALID_EVIDENCE, exit 1

## Weryfikacja ręczna (niezależnie od agenta)

`<venv-python>` to interpreter z venv utworzonego przez setup.py:
- Windows: `.test-agent\.venv\Scripts\python.exe`
- Linux/macOS: `.test-agent/.venv/bin/python`

```bash
<venv-python> .github/agents/test-planner/scripts/compute_confidence.py .test-agent/plans/<Target>/plan-v<N>.md --write
<venv-python> .github/agents/common/scripts/validate_plan.py .test-agent/plans/<Target>/plan-v<N>.md .github/agents/test-planner/schemas/test-plan.schema.json
```

Exit code walidatora: 0 = plan poprawny, 1 = INVALID_ARTIFACT.

## Jak ocenić, czy Planner działa dobrze (checklista PoC)

Po wygenerowaniu planu sprawdź:

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

## Kalibracja

- Wagi evidence: `WEIGHTS` w `compute_confidence.py` — jedno miejsce, jawne.
- Próg confidence: default 0.7; nadpisz w `.test-agent/project-profile.json`:
  ```yaml
  confidence:
    threshold: 0.75
  ```

## Znane uproszczenia PoC (świadome)

- Brak czynnika świeżości w confidence (wejdzie z detekcją STALE, D9).
- Brak Project Knowledge — każdy run robi discovery od zera.
- validate_repository wykonywane przez agenta wg instrukcji, nie jako
  osobny skrypt (do wydzielenia w V1).
