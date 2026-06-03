# DOT TrendFollowingV2 Runtime Smoke

- generated_at_utc: `2026-06-03T12:51:27.305358+00:00`
- run_id: `20260603_142706`
- process_returncode: `0`
- shutdown_classification: `close_flush_done_pending_positions_zero`
- final_classification: `DOT_ENTRY_BLOCKED_BY_RUNTIME_GATE`
- admission_blocker: `no_runtime_profile`

## Scope
- candidate: `DOTUSDTM:TrendFollowingV2:sell`
- mode: `KuCoin PAPER, LIVE=0, USE_MOCK=0`

## Command
`$env:LIVE='0'; $env:USE_MOCK='0'; $env:RUN_SYMBOLS='DOTUSDTM'; $env:ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST='DOTUSDTM:TrendFollowingV2:sell'; $env:SEED_TRADES_ENABLE='0'; $env:PAPER_AUTO_OPEN_STARTUP_ENABLE='0'; $env:PAPER_AUTO_OPEN_FALLBACK_ENABLE='0'; $env:ENTRY_ALLOWLIST_DIAGNOSTIC_FORCE_OPEN='0'; $env:ALPHA_WHITELIST_FALLBACK_ENABLE='0'; $env:DIAGNOSTIC_MODE='0'; python scripts\controlled_kpi_run.py --variant-only after --after-min 20 --symbols DOTUSDTM --market-type futures --engine v2 --paper-auto-open --run-id 20260603_142706 --after-env RUN_SYMBOLS=DOTUSDTM --after-env ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST=DOTUSDTM:TrendFollowingV2:sell --after-env SEED_TRADES_ENABLE=0 --after-env PAPER_AUTO_OPEN_STARTUP_ENABLE=0 --after-env PAPER_AUTO_OPEN_FALLBACK_ENABLE=0 --after-env ENTRY_ALLOWLIST_DIAGNOSTIC_FORCE_OPEN=0 --after-env ALPHA_WHITELIST_FALLBACK_ENABLE=0 --after-env DIAGNOSTIC_MODE=0 --after-env USE_MOCK=0 --after-env LIVE=0 --after-env ALLOW_ONE_SIDED_VALIDATION=1 --after-env PAPER_AUTO_OPEN_REQUIRE_EXPLICIT_SIDE_ALLOWLIST=1`

## Counts
- position_open_count: `0`
- position_open_v2_count: `0`
- completed_trade_count: `0`
- net_pnl: `0.0`
- winrate: `0.0`
- profit_factor: `0.0`
- expectancy: `0.0`

## Gate Reason Distribution
- no_runtime_profile: `455`
- symbol_strategy_side_allowlist: `41`
- entry_edge_filtered: `12`
- entry_min_net_guard: `4`

## No-entry Reason Distribution
- no_runtime_profile: `455`
- symbol_strategy_side_allowlist: `41`
- entry_edge_filtered: `12`
- entry_min_net_guard: `4`

## Contamination Checks
- assisted_seed_open_count: `0`
- fallback_open_count: `0`
- diagnostic_force_open_count: `0`
- mock_quote_count: `0`
- forced_cycle_or_cycle_end_events: `{}`
- contaminating_event_counts: `{}`
- log_error_count: `0`
- use_mock: `False`
- data_check_real_quote_path_ok: `True`

## Final Classification
`DOT_ENTRY_BLOCKED_BY_RUNTIME_GATE`

## Next Recommended Action
Perform entry-gate component autopsy only; do not patch strategy or thresholds until no_runtime_profile / entry_min_net_guard path is isolated.
