# CHANGELOG.md — ZoL0 AI Trading System

## 2026-04-20
- Fresh paper readiness gate ran (09:23–09:32 UTC): `paper_readiness_gate_20260420_072346`. All 4 KPI corridors passed (ETH, BTC+SOL, BTC, XRP). `operational_gate_status=PASS`, `global_verdict=PROMOTE_CANDIDATE`, `paper_ready=True`, `economics_go_no_go=GO`, `runs_passed=4/4`. `latest_gate.json` / `latest_gate.md` updated. Gate artifact: `reports/paper_readiness/paper_readiness_gate_20260420_072346.md`.
- Completed autonomous PAPER corridor validation of the post-green protective exit runtime contract patch (frozen state: `POST_GREEN_RUNTIME_CONTRACT_FIXED`).
- Conducted 17 PAPER corridor runs (batches 1–10g) on KuCoin futures, all runtime-clean (`shutdown_classification=close_flush_done_pending_positions_zero`, `process_returncode=0`).
- Confirmed `post_green_protective_terminal_trigger_seen=True` in `position_close` events for 5 of 7 closes in batch10g (ETHUSDTM, SOLUSDTM, XRPUSDTM, BTCUSDTM).
- Validated all 6 required attribution fields non-null and consistent between `position_close` and `post_green_protective_exit_terminal_outcome` events: `post_green_attempt_seq`, `post_green_branch_seq`, `post_green_trigger_mode`, `post_green_trigger_reason_detail`, `post_green_peak_to_burden_ratio`, `post_green_bnr_time_forced_exit_sec`.
- Audit artifact updated: `verdict=CONTRACT_PATCH_VALIDATED_POST_GREEN_TRIGGERED`, `audit_status=CONTRACT_VALIDATED_TRIGGERED_CLOSE_OBTAINED`. Full record at `artifacts/diagnostics/post_green_natural_entry_contract_audit_20260419_expanded.json`.
- Key finding: `EXIT_CLOSE_ATTEMPT_FEE_GUARD_COOLDOWN_SEC` default of 300s can suppress post_green_protective_exit for up to 300s after a `BLOCK_FEE_GUARD` event; future validation runs should override with `EXIT_CLOSE_ATTEMPT_FEE_GUARD_COOLDOWN_SEC=10`.
- `BotCore.py` remains frozen at `POST_GREEN_RUNTIME_CONTRACT_FIXED`; no source changes were made.

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
