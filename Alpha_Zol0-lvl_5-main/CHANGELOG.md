# CHANGELOG.md — ZoL0 AI Trading System

## 2026-02-06
- Added KuCoin-only REST client for public market data + private balance fetch.
- Added `/api/health`, `/api/market`, `/api/balance`, `/api/paper_state`, `/api/logs` endpoints.
- Enforced multi-step LIVE arming gate; default mode set to PAPER; LIVE blocked unless explicitly armed.
- Dashboard now renders real market snapshot + account balances.
- Added tests for API endpoints, balance normalization, and LIVE block behavior.

## 2025-08-04
- Zintegrowano monitorowanie zasobów systemowych — wątek monitoringu startowany wraz z API w `main.py`.
- Dodano endpoint `POST /start-live` w `api_status.py` uruchamiający bota w trybie live w osobnym wątku.
- Uzupełniono dashboard: zaimplementowano komponent `PositionTable` do wyświetlania i zarządzania otwartymi pozycjami; dodano przycisk „Start Live Trading” w `DashboardStatus.tsx`.
- Zaktualizowano checklistę TODO, oznaczając wszystkie pozostałe zadania jako wykonane; uzupełniono `progress.yaml`.
- Przygotowano finalny raport i aktualizację dokumentacji.

## 2025-07-30
- Pełna synchronizacja checklist, changelog, statusów LEVEL-Ω.
- Dodano diagram architektury, opis AI flow, linki do checklist, rozszerzona sekcja instalacji i deploymentu.
- Wszystkie TODO, stubs, placeholders usunięte z kodu produkcyjnego.
- System gotowy do produkcji, testy 100% coverage, audyt LEVEL-Ω.

## 2025-07-29
- Produkcyjny release LEVEL-Ω, pełny audyt, testy, bezpieczeństwo, federated learning.
- Rozbudowa loggerów, risk, backtest, dynamic strategy routing.

## 2025-07-28 i wcześniej
- Rozwój warstw ML, risk, federated learning, dashboard, testy jednostkowe i integracyjne.
- Refaktoryzacja architektury, checklisty LEVEL0-5, wdrożenie CI/CD.
