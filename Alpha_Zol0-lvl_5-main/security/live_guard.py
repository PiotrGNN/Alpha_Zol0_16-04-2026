# live_guard.py - centralized LIVE readiness gate (KuCoin-only)
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LIVE_BLOCKED_NOT_READY = "LIVE_BLOCKED_NOT_READY"
LIVE_READY_MIN_TRADES = 60
LIVE_READY_SHUTDOWN_CLASSIFICATION = "close_flush_done_pending_positions_zero"
LIVE_READY_CRITICAL_BLOCKERS = (
    "CLOSE_FINALIZATION_BROKEN",
    "LINKAGE_LAYER_NO_EFFECT",
    "TERMINAL_TIMING_CUTOFF_CONFIRMED",
)


def _snapshot_path(path: str | Path | None = None) -> Path:
    raw = path or os.getenv("LIVE_READINESS_SNAPSHOT_PATH", "")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.cwd() / "tmp" / "live_readiness_snapshot.json").resolve()


def _dedupe(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for item in items:
        text = str(item or "").strip()
        if text and text not in seen:
            out.append(text)
            seen.add(text)
    return out


def _safe_int(value: Any, default: int | None = None) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return default
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return default
        number = float(value)
        if math.isnan(number):
            return default
        return number
    except Exception:
        return default


def _explicit_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value == 1:
            return True
        if value == 0:
            return False
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "y", "on"}:
            return True
        if text in {"false", "0", "no", "n", "off"}:
            return False
    return None


def _runtime_section(state: dict[str, Any]) -> dict[str, Any]:
    section = state.get("last_run") or state.get("runtime_integrity") or {}
    return section if isinstance(section, dict) else {}


def _data_section(state: dict[str, Any]) -> dict[str, Any]:
    section = state.get("data_validity") or {}
    return section if isinstance(section, dict) else {}


def _metrics_section(state: dict[str, Any]) -> dict[str, Any]:
    validation = state.get("strategy_validation") or {}
    if not isinstance(validation, dict):
        validation = {}
    metrics = (
        validation.get("profitability_metrics")
        or validation.get("metrics")
        or state.get("profitability_metrics")
        or state.get("global_kpis")
        or {}
    )
    return metrics if isinstance(metrics, dict) else {}


def _strategy_validation_section(state: dict[str, Any]) -> dict[str, Any]:
    validation = state.get("strategy_validation") or {}
    return validation if isinstance(validation, dict) else {}


def _blockers_section(state: dict[str, Any]) -> dict[str, Any]:
    blockers = state.get("critical_blockers") or state.get("blockers") or {}
    return blockers if isinstance(blockers, dict) else {}


def _readiness_state(state: dict[str, Any]) -> dict[str, Any]:
    runtime_state = state.get("runtime_state") if isinstance(state, dict) else None
    if isinstance(runtime_state, dict):
        return runtime_state
    return state if isinstance(state, dict) else {}


def _lookup_int(
    section: dict[str, Any],
    fallback: dict[str, Any],
    key: str,
) -> int | None:
    value = section.get(key)
    if value is None:
        value = fallback.get(key)
    return _safe_int(value, None)


def evaluate_live_readiness_contract(
    state: dict[str, Any],
    *,
    strict_mode: bool | None = None,
) -> dict[str, Any]:
    runtime_state = _readiness_state(state)
    strict = (
        os.getenv("LIVE_READY_STRICT", "1") != "0"
        if strict_mode is None
        else bool(strict_mode)
    )
    reasons: list[str] = []
    checks: dict[str, Any] = {}

    state_load_error = str(runtime_state.get("state_load_error") or "").strip()
    if state_load_error:
        reasons.append(state_load_error)

    runtime = _runtime_section(runtime_state)
    final_drain = runtime.get("final_close_drain_snapshot") or {}
    if not isinstance(final_drain, dict):
        final_drain = {}

    process_returncode = _safe_int(runtime.get("process_returncode"), None)
    checks["process_returncode"] = process_returncode
    if process_returncode is None:
        reasons.append("process_returncode_missing")
    elif process_returncode != 0:
        reasons.append("process_returncode_nonzero")

    shutdown_classification = str(runtime.get("shutdown_classification") or "").strip()
    checks["shutdown_classification"] = shutdown_classification
    if shutdown_classification != LIVE_READY_SHUTDOWN_CLASSIFICATION:
        reasons.append("shutdown_classification_not_clean")

    pending_positions = _lookup_int(runtime, final_drain, "pending_positions")
    checks["pending_positions"] = pending_positions
    if pending_positions is None:
        reasons.append("pending_positions_missing")
    elif pending_positions != 0:
        reasons.append("pending_positions_nonzero")

    close_request_backlog = _lookup_int(
        runtime,
        final_drain,
        "close_request_backlog",
    )
    checks["close_request_backlog"] = close_request_backlog
    if close_request_backlog is None:
        reasons.append("close_request_backlog_missing")
    elif close_request_backlog != 0:
        reasons.append("close_request_backlog_nonzero")

    data = _data_section(runtime_state)
    accepted_corpus_exists = _explicit_bool(data.get("accepted_corpus_exists"))
    checks["accepted_corpus_exists"] = accepted_corpus_exists
    if accepted_corpus_exists is not True:
        reasons.append("accepted_corpus_missing")

    no_rejected = _explicit_bool(data.get("no_rejected_runs_in_active_dataset"))
    rejected_run_count = _safe_int(data.get("rejected_run_count"), None)
    if no_rejected is None and rejected_run_count is not None:
        no_rejected = rejected_run_count == 0
    checks["no_rejected_runs_in_active_dataset"] = no_rejected
    checks["rejected_run_count"] = rejected_run_count
    if no_rejected is not True:
        reasons.append("rejected_runs_present_or_unconfirmed")

    corpus_size_trades = _safe_int(
        data.get("corpus_size_trades", data.get("accepted_corpus_total_trade_count")),
        None,
    )
    checks["corpus_size_trades"] = corpus_size_trades
    checks["min_corpus_size_trades"] = LIVE_READY_MIN_TRADES
    if corpus_size_trades is None:
        reasons.append("accepted_corpus_trade_count_missing")
    elif corpus_size_trades < LIVE_READY_MIN_TRADES:
        reasons.append("accepted_corpus_below_min_trades")

    strategy_validation = _strategy_validation_section(runtime_state)
    usable_strategy_economics = _explicit_bool(
        strategy_validation.get("usable_strategy_economics")
    )
    strategy_evidence_classification = str(
        strategy_validation.get("strategy_evidence_classification") or ""
    ).strip()
    economic_go_no_go = str(
        strategy_validation.get("economic_go_no_go") or ""
    ).strip().upper()
    checks["usable_strategy_economics"] = usable_strategy_economics
    checks["strategy_evidence_classification"] = strategy_evidence_classification
    checks["economic_go_no_go"] = economic_go_no_go
    if usable_strategy_economics is not True:
        reasons.append("strategy_economics_not_usable")
        if strategy_evidence_classification:
            reasons.append(
                f"strategy_evidence_not_usable:{strategy_evidence_classification}"
            )
    if economic_go_no_go != "GO":
        reasons.append("economic_go_no_go_not_go")

    metrics = _metrics_section(runtime_state)
    expectancy = _safe_float(
        metrics.get("expectancy", metrics.get("avg_expectancy")),
        None,
    )
    winrate = _safe_float(metrics.get("winrate", metrics.get("avg_winrate")), None)
    profit_factor = _safe_float(
        metrics.get("profit_factor", metrics.get("avg_profit_factor")),
        None,
    )
    green_to_red_share = _safe_float(metrics.get("green_to_red_share"), None)
    checks["expectancy"] = expectancy
    checks["winrate"] = winrate
    checks["profit_factor"] = profit_factor
    checks["green_to_red_share"] = green_to_red_share
    if expectancy is None:
        reasons.append("expectancy_missing")
    if winrate is None:
        reasons.append("winrate_missing")

    blockers = _blockers_section(runtime_state)
    blocker_checks: dict[str, bool | None] = {}
    for blocker in LIVE_READY_CRITICAL_BLOCKERS:
        value = _explicit_bool(blockers.get(blocker))
        blocker_checks[blocker] = value
        if value is True:
            reasons.append(f"critical_blocker_true:{blocker}")
        elif value is not False:
            reasons.append(f"critical_blocker_unconfirmed:{blocker}")
    checks["critical_blockers"] = blocker_checks

    if strict:
        checks["strict_mode"] = True
        if profit_factor is None:
            reasons.append("profit_factor_missing_for_strict_mode")
        elif profit_factor <= 1.0:
            reasons.append("profit_factor_not_above_one")
        if green_to_red_share is None:
            reasons.append("green_to_red_share_missing_for_strict_mode")
        elif green_to_red_share >= 0.5:
            reasons.append("green_to_red_share_not_below_half")
    else:
        checks["strict_mode"] = False

    live_block_reason = _dedupe(reasons)
    return {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "live_ready": len(live_block_reason) == 0,
        "live_block_reason": live_block_reason,
        "strict_mode": strict,
        "checks": checks,
        "runtime_state": runtime_state,
    }


def is_live_ready(state: dict[str, Any]) -> bool:
    return bool(evaluate_live_readiness_contract(state).get("live_ready"))


def write_live_readiness_snapshot(
    evaluation: dict[str, Any],
    path: str | Path | None = None,
) -> Path:
    target = _snapshot_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(evaluation, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    return target


def load_live_readiness_snapshot(path: str | Path | None = None) -> dict[str, Any]:
    target = _snapshot_path(path)
    if not target.exists():
        return {
            "state_load_error": "live_readiness_snapshot_missing",
            "snapshot_path": str(target),
        }
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "state_load_error": "live_readiness_snapshot_invalid_json",
            "snapshot_path": str(target),
            "error": f"{type(exc).__name__}: {exc}",
        }
    if not isinstance(payload, dict):
        return {
            "state_load_error": "live_readiness_snapshot_not_object",
            "snapshot_path": str(target),
        }
    return payload


def enforce_live_ready(state: dict[str, Any] | None = None) -> dict[str, Any]:
    runtime_state = load_live_readiness_snapshot() if state is None else state
    evaluation = evaluate_live_readiness_contract(runtime_state)
    write_live_readiness_snapshot(evaluation)
    if not evaluation["live_ready"]:
        raise RuntimeError(LIVE_BLOCKED_NOT_READY)
    return evaluation


def is_live_armed() -> tuple[bool, str]:
    """
    Multi-step LIVE arming gate.
    LIVE trading is enabled only when ALL deterministic runtime checks pass.
    """
    if os.getenv("LIVE", "0") != "1":
        return False, "LIVE is disabled"
    if os.getenv("LIVE_ARMED", "0") != "1":
        return False, "LIVE_ARMED not set"
    if not os.getenv("ZOL0_TOKEN"):
        return False, "ZOL0_TOKEN missing"
    if not os.getenv("KUCOIN_API_KEY"):
        return False, "KUCOIN_API_KEY missing"
    if not os.getenv("KUCOIN_API_SECRET"):
        return False, "KUCOIN_API_SECRET missing"
    if not os.getenv("KUCOIN_API_PASSPHRASE"):
        return False, "KUCOIN_API_PASSPHRASE missing"
    try:
        enforce_live_ready()
    except RuntimeError as exc:
        if str(exc) == LIVE_BLOCKED_NOT_READY:
            return False, LIVE_BLOCKED_NOT_READY
        return False, str(exc)
    return True, "LIVE armed"
