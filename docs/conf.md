# Agent do generowania testów jednostkowych dla aplikacji Java / Spring Boot

## 1. Informacje podstawowe

| Atrybut | Wartość |
|---|---|
| Odbiorcy | Programiści Java |
| Cel | Automatyzacja procesu projektowania, generowania i weryfikacji testów jednostkowych |
| Lokalizacja | Repozytorium tc-agent |
| Data przeglądu | 2026-11-05 |

## 2. Wprowadzenie

Agent wspiera tworzenie i utrzymanie testów JUnit dla wskazanej klasy Java lub pojedynczej metody w klasie.

Agent realizuje pełny proces przygotowania testów:

- analizuje kod i istniejące testy,
- planuje scenariusze testowe,
- generuje testy,
- uruchamia kontrole jakości (pokrycie kodu, testy mutacyjne),
- przygotowuje raport końcowy.

Proces został podzielony na wyspecjalizowane role:

- **Planner** odpowiada za analizę i definicję scenariuszy.
- **Generator** tworzy implementację testów.
- **Reviewer** ocenia jakość wygenerowanych testów.
- **Orchestrator** koordynuje cały przepływ pracy.

Agent nie modyfikuje kodu produkcyjnego (`src/main`) i nie podejmuje decyzji biznesowych bez odpowiednich dowodów lub specyfikacji.

## 3. Obsługiwane tryby pracy

### Characterization

Domyślny tryb działania. Testy dokumentują aktualne zachowanie aplikacji wynikające bezpośrednio z implementacji, nawet jeśli to zachowanie może być uznane za niepożądane lub błędne.

Najważniejsze cechy:

- oczekiwania są wyprowadzane z istniejącego kodu,
- testowana klasa musi być zacommitowana i bez lokalnych zmian — inaczej uruchomienie kończy się statusem `BLOCKED`,
- kod młodszy niż `freshness_days` (domyślnie 7 dni) nie jest zamrażany bez trybu interactive (status `BLOCKED`) — nikt jeszcze nie potwierdził, że jego zachowanie jest poprawne,
- agent sam wykrywa testy nieaktualne (*stale*): test jest nieaktualny, gdy testowana klasa zmieniła się w gicie po ostatnim commicie tego testu. Nieaktualny, ale zielony test zostaje bez zmian; nieaktualny i czerwony wraca do planowania.

### Spec-driven

Tryb oparty o wymagania. Agent wykorzystuje wskazaną specyfikację jako źródło prawdy i generuje testy odzwierciedlające wymagane zachowanie.

- Specyfikacja jest wymagana — jeśli nie zostanie podana, orchestrator o nią dopyta.
- Plik specyfikacji może leżeć poza repozytorium albo w `.gitignore`: w kodzie testów nie zostaje do niego odwołanie.
- Niejasne albo sprzeczne wymaganie: w trybie interactive planner dopyta, bez niego uruchomienie zatrzymuje się z prośbą o doprecyzowanie (`NEEDS_CLARIFICATION`).

Jeżeli implementacja jest niezgodna ze specyfikacją:

- test pozostaje zgodny ze specyfikacją (jego treść nie jest zmieniana),
- test zostaje wyłączony adnotacją `@Disabled("AI spec-mismatch: …")`,
- rozbieżność zostaje wymieniona na początku raportu.

### Interactive

Opcjonalny modyfikator obu trybów (`--interactive`).

Pozwala użytkownikowi:

- dostarczyć brakujące dane wejściowe,
- rozstrzygać niejednoznaczności,
- potwierdzać zamrożenie aktualnego zachowania,
- podejmować decyzje blokujące dalsze planowanie.

W trybie characterization interactive wyłącza też blokadę zbyt świeżego kodu.

## 4. Architektura rozwiązania

Zasada: **modele językowe decydują o treści, skrypty decydują o przebiegu.** Planner, generator i reviewer to agenci LLM; kolejność kroków, limit rund, stan celu, pomiary (Maven, JaCoCo, PIT) i commit obsługują deterministyczne skrypty Pythona — model nie ocenia sam swoich testów.

*(tu wstaw diagram `docs/architecture.svg` z repozytorium tc-agent)*

| Komponent | Odpowiedzialność |
|---|---|
| `tc-orchestrator.agent.md` | Główny punkt wejścia i koordynacja procesu |
| `tc-planner.agent.md` | Projektowanie scenariuszy testowych |
| `tc-generator.agent.md` | Generowanie kodu testów |
| `tc-reviewer.agent.md` | Walidacja jakości oraz zgodności z planem |
| `tc_orchestrate.py` | Zarządzanie przebiegiem uruchomienia (maszyna stanów, limit rund, raport, commit) |
| `tc_derive_state.py` | Analiza aktualnego stanu celu |
| pozostałe skrypty | Context pack, uruchamianie testów, JaCoCo, PIT, weryfikacja planu — pełny opis każdego pliku w sekcji *Files* pliku `README.md` |

Wymiana informacji pomiędzy rolami odbywa się wyłącznie przez artefakty zapisywane dla konkretnego uruchomienia (`.test-agent/runs/<cel>/<run-id>/`).

Przy każdym nowym uruchomieniu rzeczywisty stan wyznaczany jest ponownie na podstawie:

- kodu źródłowego,
- istniejących testów,
- historii Git,
- wyników pomiarów jakościowych.

Agent nie pamięta niczego między uruchomieniami.

## 5. Konfiguracja w repozytorium projektowym

Agent był tworzony tak, aby nie był związany z konkretnym projektem. Poprawność działania została potwierdzona na kilku różnych repozytoriach.
Z uwagi na używany stack technologiczny rozwiązanie zostało przygotowane dla aplikacji w stacku: Java / Spring Boot / Maven.

**Wymagania wstępne:**

- projekt Maven z testami JUnit 5 lub JUnit 4 (wersję agent rozpoznaje sam),
- git,
- Python 3 oraz `pip install -r .github/agents/tc-agent/requirements.txt`,
- GitHub Copilot z włączonymi custom agents,
- biblioteki testowe: JUnit, Mockito, AssertJ (domyślny styl testów) — np. przez `spring-boot-starter-test`:

```xml
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-test</artifactId>
    <scope>test</scope>
</dependency>
```

**Konfiguracja w pom:**

JaCoCo i PIT nie wymagają wpisów w pom — agent wywołuje je z linii komend (wersja zadeklarowana w pom ma pierwszeństwo przed domyślną wersją agenta).

Wyjątek: przy **JUnit 5** PIT potrzebuje `pitest-junit5-plugin`. Bez niego testy mutacyjne są raportowane jako niedostępne. Wystarczy zwykła zależność testowa:

```xml
<dependency>
    <groupId>org.pitest</groupId>
    <artifactId>pitest-junit5-plugin</artifactId>
    <version>${pitest.junit5.plugin.version}</version>
    <scope>test</scope>
</dependency>
```

Wersję `pitest-junit5-plugin` dobieramy zgodnie z wersją PIT (domyślną wersję agenta albo zadeklarowaną w pom). Przy JUnit 4 ta zależność nie jest potrzebna.

Jeśli w projekcie wielomodułowym Maven przerywa build komunikatem, że w module nie wykonano żadnego testu, ustaw w Surefire:

```xml
<plugin>
    <groupId>org.apache.maven.plugins</groupId>
    <artifactId>maven-surefire-plugin</artifactId>
    <version>${surefire.plugin.version}</version>
    <configuration>
        <failIfNoSpecifiedTests>false</failIfNoSpecifiedTests>
    </configuration>
</plugin>
```

**Instalacja agenta:**

Folder `tc-agent` z repozytorium tc-agent zapisujemy w projekcie jako `.github/agents/tc-agent`. Aktualizacja agenta to podmiana tego folderu w całości — nic w nim nie edytujemy.

**Opcjonalne ustawienia projektowe:**

Agent działa bez konfiguracji — każde ustawienie ma wartość domyślną. Aby coś zmienić, tworzymy w `.github` folder `tc-agent-project-config` i umieszczamy w nim tylko potrzebne pliki:

```
.github/
├── agents/tc-agent/               ← agent, podmieniany w całości
└── tc-agent-project-config/       ← opcjonalny, ustawienia tego projektu
    ├── profile.md                 ← wartości inne niż domyślne (progi, rundy, chronione branche, maven)
    ├── conventions.md             ← styl testów tego projektu
    └── test-data-examples.md      ← przykładowe wartości biznesowe (format id, numeru rachunku…)
```

Przykład każdego pliku i opis wszystkich ustawień: `docs/configuration.md` w repozytorium agenta. Plik o nazwie, której agent nie zna, jest zgłaszany ostrzeżeniem przy starcie.

**Ważne:**
Agent w trakcie pracy tworzy pliki pomocnicze w `.test-agent` — ten folder trzeba dodać do `.gitignore`. Jest tam cały przebieg tworzenia testów, ale nie powinien on trafiać do repozytorium.

## 6. Przebieg działania

**Człowiek:** wskazanie klasy lub metody w klasie i wywołanie agenta.
**Agent:** analiza stanu i zebranie kontekstu → planowanie scenariuszy → generowanie testów lub placeholderów → review i kontrole jakości → akceptacja / poprawa / eskalacja → raport końcowy → opcjonalny commit zmian.

W trakcie analizy agent identyfikuje:

- moduł Maven,
- istniejące testy,
- historię zmian,
- metadane testów.

W tym kroku w razie potrzeby uruchamiane są pomiary JaCoCo i PIT.

W trakcie planowania definiowane są:

- scenariusze testowe,
- oczekiwane wyniki,
- wykorzystywane dowody,
- przypadki wymagające odroczenia.

W trakcie generowania testów tworzone są:

- testy JUnit,
- metadane Javadoc,
- placeholdery dla scenariuszy niemożliwych do automatycznego wykonania.

Test wygenerowany przez agenta ma dwulinijkowy Javadoc:

```java
/**
 * AI-generated test. Characterizes current behavior of OrderService (a freeze, not a spec).
 * tc-agent-mode: characterization, interactive: false
 */
```

W trakcie review weryfikowane są:

- poprawność wykonania testów (w tym testy niestabilne — flaky),
- zgodność z planem,
- poziom pokrycia,
- wyniki analizy mutacyjnej PIT.

Finalna decyzja, możliwe wyniki:

| Wynik | Znaczenie |
|---|---|
| `DONE` | testy przechodzą, progi jakości spełnione |
| `DONE_PARTIAL` | jak DONE, ale zostały placeholdery (świadomie nieprzetestowane scenariusze) |
| `BLOCKED` | characterization: klasa niezacommitowana, zmieniona lokalnie albo zbyt świeża |
| `RED` | istniejące testy nie przechodzą — człowiek musi to sprawdzić |
| `ESCALATED` | wyczerpany limit rund albo potrzebna decyzja człowieka |

Domyślnie jedno uruchomienie obejmuje maksymalnie 3 rundy (generowanie + review); limit można zmienić w poleceniu albo w `profile.md` (`max_rounds`).

## 7. Źródła dowodów

Podczas planowania agent może korzystać z następujących źródeł:

- implementacja klasy,
- istniejące testy,
- fixture'y,
- buildery,
- enumy,
- przykłady danych (`test-data-examples.md` i pliki wskazane w poleceniu),
- zależności projektowe,
- specyfikacje funkcjonalne,
- decyzje użytkownika.

Agent nie wymyśla wartości, od której zależy wynik testu — oczekiwania muszą wynikać z dostępnych dowodów. Wartości, które tylko przechodzą przez kod (np. identyfikator porównywany z innym), mogą być neutralne.
Jeżeli nie istnieje możliwość stworzenia wiarygodnego i deterministycznego testu, scenariusz zostaje odroczony zamiast generowania pozornej walidacji.

## 8. Kontrole jakości

**Maven / Surefire**

- kompilacja testów,
- wykonanie testów,
- wykrywanie niestabilności (flaky tests).

**JaCoCo**

Pomiar pokrycia wskazanej klasy lub metody:

- linie kodu,
- gałęzie warunkowe (ten wskaźnik jest progiem jakości).

**PIT Mutation Testing**

Analiza skuteczności testów poprzez generowanie mutantów. Uruchamiane, gdy testy przechodzą i spełniony jest próg pokrycia. Zakres mutacji obejmuje tylko wskazaną klasę lub metodę.

**Review scenariuszy**

Dodatkowa walidacja obejmująca:

- zgodność z planem,
- jakość asercji,
- identyfikację nieobsłużonych przypadków.

## 9. Domyślne progi jakości

| Metryka | Wartość |
|---|---|
| Pokrycie gałęzi (branch coverage) | 80% |
| Mutation Score | 70% |

Ważne:

- progi dotyczą wskazanej klasy lub metody, nie całego projektu,
- przedstawione wartości są wartościami domyślnymi, które można dostosować do projektu (`profile.md`),
- niewykonalna kontrola nie oznacza zaliczenia progu,
- brak mutantów raportowany jest osobno,
- wysokie pokrycie nie gwarantuje poprawności testów.

## 10. Placeholdery i scenariusze odroczone

Jeżeli scenariusz nie może zostać zweryfikowany w sposób wiarygodny, agent generuje jawny placeholder — pustą metodę testową z:

- `@Disabled("AI deferred: …")` (JUnit 5),
- `@Ignore("AI deferred: …")` (JUnit 4),
- powodem w Javadocu (`tc-agent-deferred: …`).

Dzięki temu luka testowa pozostaje widoczna podczas kolejnych uruchomień. Placeholderów nie usuwamy bez powodu — mówią kolejnemu uruchomieniu, że luka jest znana.

Raport końcowy (`run-report.md`) zawiera:

- status wykonania,
- wyniki kontroli jakości,
- wygenerowane testy,
- placeholdery,
- rozbieżności ze specyfikacją,
- pytania do potwierdzenia przez człowieka (`CONFIRM`),
- rekomendowane działania dla użytkownika.

## 11. Uruchamianie

Wybieramy agenta **tc-orchestrator** i wpisujemy, czego oczekujemy, np.:

```
Generate tests for SimpleCalculatorService, mode characterization, commit
Generate tests for OrderService.create, mode spec-driven, spec docs/order-spec.md, interactive
Generate tests for TransferService, data examples in docs/test-data-examples.md
```

| Opcja | Znaczenie |
|---|---|
| cel | `NazwaKlasy` albo `NazwaKlasy.metoda`; jeden albo lista |
| `mode characterization` / `mode spec-driven` | tryb pracy (domyślnie characterization) |
| `spec <plik>` | specyfikacja — wymagana w spec-driven |
| `interactive` | planner może zadawać pytania |
| `data examples in <plik>` | plik z przykładowymi wartościami biznesowymi |
| `max rounds <n>` | limit rund dla tego uruchomienia |
| `commit` | commit nowych testów na końcu (patrz sekcja 12) |

## 12. Bezpieczeństwo zmian

W aktualnym rozwiązaniu agent:

- może tworzyć i modyfikować testy,
- może wykonać lokalny commit — tylko na żądanie (`commit`), tylko przy wyniku `DONE` / `DONE_PARTIAL` i tylko pliki spod `src/test`,
- na chronionym branchu (domyślnie `master` i `main`) najpierw tworzy nowy branch `tc-agent/<cel>/<run-id>`,
- nie modyfikuje kodu produkcyjnego,
- nie wykonuje `git push`,
- nie omija bramek jakości,
- nie zastępuje code review.

W przypadku wykrycia zmian w `src/main` podczas trwania procesu uruchamiana jest eskalacja zamiast dalszego przetwarzania.

## 13. Ograniczenia

Należy pamiętać, że:

- analiza projektu jest częściowo statyczna,
- paczka kontekstu posiada ograniczenia rozmiaru,
- obsługiwany jest tylko Maven (bez Gradle),
- jedno uruchomienie dotyczy jednej klasy albo metody,
- testy mutacyjne (PIT) w dużych modułach mogą trwać kilka minut,
- w trakcie przebiegu Copilot może otwierać wiele sesji terminala,
- nietypowe projekty mogą wymagać ręcznej weryfikacji,
- pokrycie kodu oraz mutation score nie stanowią dowodu poprawności wymagań biznesowych.

## 14. Metryki

Aktualnie zbierane są dane odnośnie:

- oszczędności czasu,
- kosztów wykorzystania AI (w zależności od modelu),
- skuteczności na szerokiej próbce projektów.

Źródłem danych jest raport `run-report.md` z każdego uruchomienia: liczba wygenerowanych testów i placeholderów, liczba rund, wyniki progów jakości oraz czas wykonania kontroli Maven.

Takie dane mogą zostać określone dopiero po dłuższym okresie wykorzystania agenta.

Wstępne wyniki:
todo …