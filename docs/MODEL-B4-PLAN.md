# tc-agent — model B4

> **Gałąź:** `model-b4`, od tagu `model-b2-final`. **Powód (2026-11-02/03):** na prawdziwych celach użytkownika
> B2 dał wyraźnie lepszy wynik niż B3 (mniej zaślepek, lepiej prowadzona pętla). B3 zostaje na `model-b3`.

## Zasada

Bazą jest B2. Z B3 wchodzą tylko zmiany, które nie zmieniają zachowania modeli ani pętli. Każda zmiana
promptu, schematu, pakietu kontekstu albo pętli wraca dopiero wtedy, gdy przebieg na tym samym celu
pokaże, że nie pogarsza wyniku (tyle samo lub mniej zaślepek, nie więcej rund).

## Przeniesione z B3

| commit | co |
|---|---|
| `c3e5425` | nazwy: `slug` → `target` (`target_name` w JSON), `test-data.md` → `test-data-examples.md`, jeden katalog projektu `.github/agents/tc-agent-project/`; ostrzeżenie `start` o plikach projektu, których agent nie czyta |
| `a6d745a` | poprawki skryptów (B3 E2): flaky vs failed, lambdy w zakresie metody, statusy PIT, brakujące zależności przed PIT, `@DisabledOn…`, wersje `${property}`, porządki |
| `0cc616d` | commit tylko plików spod `src/test`; odmowy `start`: `SPEC_REQUIRED`, `FILE_NOT_FOUND`, `INVALID_PROFILE` |
| `5097543` | dokumentacja (README z opisem plików, tabela kluczy, diagram), `protected_branches` domyślnie `master` + `main` |

Prompty ról, `references/` i schematy różnią się od B2 tylko nazwami oraz dwoma zdaniami orkiestratora
(ostrzeżenia `start`, `SPEC_REQUIRED`).

## Nie przeniesione (kandydaci, każdy osobno i tylko po porównaniu)

- plan naprawczy tylko ze zmianami, generator bez recenzji przy nowym planie, `gate_checks` (B3 E0, D98);
- `COMPLETE` tylko w pierwszej wersji planu; ESCALATED przy zmianie dowolnego pliku poza `src/test`;
  wczesne BLOCKED dla brudnego / niezacommitowanego celu (B3 E1);
- pakiet: rezerwa na target i spec, weryfikacja każdego refu w kształcie ścieżki, cytowanie spec (B3 E3);
- odchudzone schematy (B3 E3b);
- spec-driven: tylko testy w derive-state, PIT zawsze przy zielonych testach;
- zmiany z 2026-11-02: §A4 (walidator w repo, jeden przykład → pole walidowane), §B5 (mock walidatorów),
  klasy bazowe w pakiecie, escape hatch bez `BLOCKED`, wspólne pytanie CONFIRM, `state` budujący brakujący pakiet.
