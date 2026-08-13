# tests-app
Prosta aplikacja Spring Boot do rezerwacji wizyt, z warstwami:
- `controller`
- `service`
- `repository`
Repozytoria sa pamieciowe i oparte o `HashMap` / `ConcurrentHashMap`.
## Uruchomienie
```powershell
mvn spring-boot:run
```
## Glówne endpointy
### Uslugi
- `GET /api/service-offers`
- `GET /api/service-offers/active`
- `GET /api/service-offers/{id}`
- `POST /api/service-offers`
- `PATCH /api/service-offers/{id}/activate`
- `PATCH /api/service-offers/{id}/deactivate`
### Wizyty
- `GET /api/appointments`
- `GET /api/appointments/{id}`
- `POST /api/appointments`
- `POST /api/appointments/{id}/cancel`
- `POST /api/appointments/{id}/reschedule`
- `GET /api/appointments/availability?serviceOfferId=1&date=2026-08-13`
- `GET /api/appointments/dashboard`
## Reguly biznesowe
- godziny pracy: 09:00-17:00,
- wizyty tylko co 15 minut,
- minimum 2 godziny wyprzedzenia,
- maksymalnie 90 dni do przodu,
- maksymalnie 3 przyszle wizyty na klienta,
- anulowanie tylko na ponad godzine przed terminem,
- uslugi mozna wylaczyc tylko, jesli nie maja aktywnych przyszlych wizyt.
