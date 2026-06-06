from __future__ import annotations

import json
import os
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.db_models import init_db
from core.runtime_v2.calibration_gate import (
    evaluate_expected_move_calibration_gate,
    load_expected_move_calibration_profile,
)
from core.runtime_v2.admission_reachability import (
    admission_reachability_profile_payload,
)
from core.runtime_v2.contracts import StrategySignal
from core.runtime_v2.data_feed import KucoinPaperDataFeed
from core.runtime_v2.decision_engine import DecisionEngineV2
from core.runtime_v2.execution_engine import PaperExecutionEngineV2
from core.runtime_v2.exit_engine import ExitEngineV2
from core.runtime_v2.feature_engine import FeatureEngine
from core.runtime_v2.immediate_adverse_shadow import ImmediateAdverseShadowTracker
from core.runtime_v2.post_signal_trajectory import PostSignalTrajectoryTracker
from core.runtime_v2.risk_engine import RiskEngineV2
from core.runtime_v2.strategy_stack import StrategyStack
from core.runtime_v2.telemetry import TelemetryV2


ANALYSIS_DIR = Path(__file__).resolve().parents[2] / "analysis"


def _env_flag(name: str, default: str = "0") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except Exception:
        return float(default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return int(default)


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _shadow_reachability_payload(
    *,
    risk_candidate_seen_count: int,
    shadow_candidate_registered_count: int,
    shadow_terminal_outcome_count: int,
    shadow_registration_skipped_count: int,
    shadow_registration_skip_reasons: Dict[str, int],
    shadow_terminal_classifications: Dict[str, int],
) -> Dict[str, Any]:
    classifications = dict(shadow_terminal_classifications or {})
    return {
        "risk_candidate_seen_count": int(risk_candidate_seen_count),
        "shadow_candidate_registered_count": int(shadow_candidate_registered_count),
        "shadow_terminal_outcome_count": int(shadow_terminal_outcome_count),
        "shadow_open_at_shutdown_count": int(
            classifications.get("SHADOW_OPEN_AT_SHUTDOWN", 0)
        ),
        "shadow_expired_no_terminal_move_count": int(
            classifications.get("SHADOW_EXPIRED_NO_TERMINAL_MOVE", 0)
        ),
        "shadow_insufficient_quotes_count": int(
            classifications.get("SHADOW_INSUFFICIENT_QUOTES", 0)
        ),
        "shadow_registration_skipped_count": int(shadow_registration_skipped_count),
        "shadow_registration_skip_reason_distribution": dict(
            sorted(dict(shadow_registration_skip_reasons or {}).items())
        ),
    }


def _shadow_verified_guard_fields_from_trace(sizing_trace: Dict[str, Any]) -> Dict[str, Any]:
    fields = {
        key: value
        for key, value in dict(sizing_trace or {}).items()
        if key.startswith("shadow_verified_guard_")
    }
    if not bool(fields.get("shadow_verified_guard_evaluated")):
        return {}
    return fields


def _derive_exit_controls(
    *,
    base_take_profit_net_usdt: float,
    base_stop_loss_net_usdt: float,
    base_max_hold_sec: float,
    expected_net_after_full_cost_usdt: float,
    signal_horizon_ticks: Optional[float],
    loop_sleep_sec: float,
    use_expected_targets: bool,
    tp_expected_mult: float,
    sl_expected_mult: float,
    tp_min_usdt: float,
    sl_min_usdt: float,
    horizon_mult: float,
    min_hold_sec: float,
) -> Dict[str, Optional[float]]:
    signal_horizon_sec_estimate = None
    if signal_horizon_ticks is not None and signal_horizon_ticks > 0:
        signal_horizon_sec_estimate = float(signal_horizon_ticks) * float(
            loop_sleep_sec
        )

    execution_horizon_sec = float(base_max_hold_sec)
    if signal_horizon_sec_estimate is not None and signal_horizon_sec_estimate > 0:
        execution_horizon_sec = min(
            float(base_max_hold_sec),
            max(float(min_hold_sec), signal_horizon_sec_estimate * float(horizon_mult)),
        )

    time_horizon_mismatch_sec = None
    time_horizon_mismatch_ratio = None
    if signal_horizon_sec_estimate is not None and signal_horizon_sec_estimate > 0:
        time_horizon_mismatch_sec = execution_horizon_sec - signal_horizon_sec_estimate
        time_horizon_mismatch_ratio = (
            execution_horizon_sec / signal_horizon_sec_estimate
        )

    take_profit_target = max(0.01, float(base_take_profit_net_usdt))
    stop_loss_target = max(0.01, float(base_stop_loss_net_usdt))
    expected_net_usdt = max(0.0, float(expected_net_after_full_cost_usdt))
    if use_expected_targets and expected_net_usdt > 0.0:
        dynamic_tp = max(
            float(tp_min_usdt), expected_net_usdt * float(tp_expected_mult)
        )
        dynamic_sl = max(
            float(sl_min_usdt), expected_net_usdt * float(sl_expected_mult)
        )
        take_profit_target = min(take_profit_target, dynamic_tp)
        stop_loss_target = min(
            stop_loss_target, max(dynamic_sl, take_profit_target * 0.90)
        )
        take_profit_target = max(0.01, take_profit_target)
        stop_loss_target = max(0.01, stop_loss_target)

    return {
        "signal_horizon_sec_estimate": signal_horizon_sec_estimate,
        "execution_horizon_sec": float(execution_horizon_sec),
        "time_horizon_mismatch_sec": time_horizon_mismatch_sec,
        "time_horizon_mismatch_ratio": time_horizon_mismatch_ratio,
        "take_profit_net_usdt": float(take_profit_target),
        "stop_loss_net_usdt": float(stop_loss_target),
    }


def _resolve_expected_move_calibration_path() -> Path | None:
    candidates = [
        ANALYSIS_DIR / "v2_clean_trade_corpus_current.json",
        ANALYSIS_DIR / "v2_expected_move_calibration_autopsy.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _parse_symbols() -> List[str]:
    raw = str(os.environ.get("RUN_SYMBOLS", "")).strip()
    if not raw:
        raw = "BTCUSDTM,SOLUSDTM,XRPUSDTM,ADAUSDTM,BNBUSDTM,DOGEUSDTM,LINKUSDTM,TRXUSDTM,DOTUSDTM,AVAXUSDTM"  # noqa: E501
    symbols = []
    seen = set()
    for token in raw.split(","):
        symbol = str(token or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
    return symbols


def _canonical_strategy_name(value: Any) -> str:
    text = "".join(ch for ch in str(value or "").strip().upper() if ch.isalnum())
    if text.endswith("V2"):
        text = text[:-2]
    return text


def _canonical_symbol_strategy_side_key(symbol: str, strategy: str, side: str) -> str:
    symbol_key = str(symbol or "").strip().upper()
    strategy_key = _canonical_strategy_name(strategy)
    side_key = str(side or "").strip().lower()
    if side_key == "long":
        side_key = "buy"
    elif side_key == "short":
        side_key = "sell"
    if not symbol_key or not strategy_key or side_key not in {"buy", "sell"}:
        return ""
    return f"{symbol_key}:{strategy_key}:{side_key}"


def _parse_symbol_strategy_side_allowlist(raw_value: str) -> set[str]:
    out: set[str] = set()
    for token in str(raw_value or "").split(","):
        text = str(token or "").strip()
        if not text:
            continue
        if ":" in text:
            parts = [part.strip() for part in text.split(":")]
        elif "|" in text:
            parts = [part.strip() for part in text.split("|")]
        else:
            continue
        if len(parts) < 3:
            continue
        key = _canonical_symbol_strategy_side_key(parts[0], parts[1], parts[2])
        if key:
            out.add(key)
    return out


def _is_allowlisted_signal(
    *,
    symbol: str,
    strategy: str,
    side: str,
    allowlist: set[str],
) -> bool:
    if not allowlist:
        return True
    key = _canonical_symbol_strategy_side_key(symbol, strategy, side)
    return bool(key and key in allowlist)


def _strategy_name_from_allowlist_key(strategy_key: str) -> str:
    key = str(strategy_key or "").strip().upper()
    mapping = {
        "TRENDFOLLOWING": "TrendFollowingV2",
        "MOMENTUM": "MomentumV2",
        "MEANREVERSION": "MeanReversionV2",
        "UNIVERSAL": "Universal",
    }
    if key in mapping:
        return mapping[key]
    return str(strategy_key or "").strip() or "Universal"


def _sqlite_path_from_database_url() -> Optional[Path]:
    database_url = str(os.environ.get("DATABASE_URL", "")).strip()
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return None
    raw_path = database_url[len(prefix) :]
    if not raw_path:
        return None
    return Path(raw_path)


class _CloseRequestPoller:
    def __init__(self, db_path: Optional[Path]):
        self.db_path = db_path
        self.last_rowid = 0

    def poll(self) -> List[dict]:
        if self.db_path is None or not self.db_path.exists():
            return []
        conn = None
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            rows = cur.execute(
                (
                    "SELECT rowid, details "
                    "FROM logs "
                    "WHERE event = ? AND rowid > ? "
                    "ORDER BY rowid ASC"
                ),
                ("position_close_request", int(self.last_rowid)),
            ).fetchall()
            out: List[dict] = []
            for row in rows or []:
                try:
                    rowid = int(row["rowid"] or 0)
                except Exception:
                    rowid = 0
                details_raw = row["details"]
                try:
                    payload = json.loads(details_raw) if details_raw else {}
                except Exception:
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                symbol = str(payload.get("symbol") or "").strip().upper()
                reason = str(payload.get("reason") or "position_close_request").strip()
                out.append({"rowid": rowid, "symbol": symbol, "reason": reason})
                if rowid > self.last_rowid:
                    self.last_rowid = rowid
            return out
        except Exception:
            return []
        finally:
            if conn is not None:
                conn.close()


def _should_block_mock() -> bool:
    if not _env_flag("USE_MOCK", "0"):
        return False
    # Unit tests may intentionally enable mock branches.
    return not bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _position_payload(
    position, close_price_hint: float, extra_meta: Optional[dict] = None
) -> dict:
    payload = {
        "symbol": position.symbol,
        "side": position.side,
        "strategy": position.strategy,
        "entry_main_strategy": position.strategy,
        "price": float(position.open_price),
        "entry_price": float(position.open_price),
        "amount": float(position.quantity_base),
        "qty": float(position.quantity_contracts),
        "leverage": float(position.leverage),
        "timestamp": float(position.opened_ts),
        "opened_at": float(position.opened_ts),
        "last_mark_price": float(close_price_hint),
        "notional_usdt": float(position.notional_usdt),
    }
    if extra_meta:
        payload["meta"] = dict(extra_meta)
    return payload


def run_bot_v2(simulate: bool = False) -> None:
    if not simulate:
        raise RuntimeError("runtime_v2 is PAPER-only and requires simulate=True")
    if _env_flag("LIVE", "0"):
        raise RuntimeError("runtime_v2 blocked: LIVE=1 is not allowed")
    if _should_block_mock():
        raise RuntimeError("runtime_v2 blocked: USE_MOCK=1 (non-test runtime)")
    market_type = str(os.environ.get("MARKET_TYPE", "futures")).strip().lower()
    if market_type != "futures":
        raise RuntimeError("runtime_v2 blocked: KuCoin futures only")

    init_db()
    symbols = _parse_symbols()
    base_balance = _env_float("PAPER_BASE_BALANCE", 1000.0)
    loop_sleep_sec = max(0.2, _env_float("V2_LOOP_SLEEP_SEC", 0.8))
    equity_snapshot_sec = max(1, _env_int("EQUITY_SNAPSHOT_SEC", 10))
    quote_stale_ms = max(0, _env_int("V2_QUOTE_STALE_MS", 5000))
    paper_auto_close_sec = max(5, _env_int("PAPER_AUTO_CLOSE_SEC", 60))
    take_profit_net_usdt = max(0.01, _env_float("V2_TAKE_PROFIT_NET_USDT", 0.03))
    stop_loss_net_usdt = max(0.01, _env_float("V2_STOP_LOSS_NET_USDT", 0.06))
    use_dynamic_exit_targets = _env_flag("V2_EXIT_USE_EXPECTED_NET_TARGETS", "1")
    exit_tp_expected_mult = max(0.10, _env_float("V2_EXIT_TP_EXPECTED_MULT", 0.85))
    exit_sl_expected_mult = max(0.10, _env_float("V2_EXIT_SL_EXPECTED_MULT", 1.10))
    exit_tp_min_usdt = max(0.001, _env_float("V2_EXIT_TP_MIN_USDT", 0.005))
    exit_sl_min_usdt = max(0.001, _env_float("V2_EXIT_SL_MIN_USDT", 0.007))
    exit_horizon_mult = max(1.0, _env_float("V2_EXIT_HORIZON_MULT", 12.0))
    exit_min_hold_sec = max(1.0, _env_float("V2_EXIT_MIN_HOLD_SEC", 8.0))
    explicit_side_allowlist = _parse_symbol_strategy_side_allowlist(
        str(os.environ.get("ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST", "") or "")
    )
    diagnostic_force_open = _env_flag("ENTRY_ALLOWLIST_DIAGNOSTIC_FORCE_OPEN", "0")
    require_explicit_side_allowlist = _env_flag(
        "PAPER_AUTO_OPEN_REQUIRE_EXPLICIT_SIDE_ALLOWLIST",
        "0",
    )
    if require_explicit_side_allowlist and not explicit_side_allowlist:
        raise RuntimeError(
            "runtime_v2 blocked: explicit side allowlist required but empty"
        )
    end_ts_env = _env_float("CONTROLLED_RUN_END_TS", 0.0)
    if end_ts_env > 0:
        run_end_ts = float(end_ts_env)
    else:
        run_end_ts = time.time() + float(max(60, _env_int("PAPER_RUN_MAX_SEC", 900)))
    paper_run_once = _env_flag("PAPER_RUN_ONCE", "0")
    calibration_gate_enabled = _env_flag(
        "V2_EXPECTED_MOVE_CALIBRATION_GATE_ENABLE",
        "1",
    )
    calibration_gate_fail_closed = _env_flag(
        "V2_EXPECTED_MOVE_CALIBRATION_GATE_FAIL_CLOSED",
        "1",
    )
    calibration_gate_min_sample = max(1, _env_int("V2_CALIBRATION_MIN_SAMPLE", 3))
    calibration_gate_min_positive_net_share = max(
        0.0,
        min(1.0, _env_float("V2_CALIBRATION_MIN_POSITIVE_NET_SHARE", 0.35)),
    )
    calibration_gate_min_expected_net = _env_float(
        "V2_CALIBRATION_MIN_EXPECTED_NET_USDT",
        0.0,
    )
    calibration_gate_max_mismatch_ratio = max(
        1.0,
        _env_float("V2_CALIBRATION_MAX_MISMATCH_RATIO", 2.5),
    )
    post_signal_trajectory_enabled = _env_flag(
        "RUNTIME_V2_POST_SIGNAL_TRAJECTORY",
        "0",
    )
    expected_move_calibration_profile = load_expected_move_calibration_profile(
        _resolve_expected_move_calibration_path()
    )

    telemetry = TelemetryV2(engine_version="v2")
    feed = KucoinPaperDataFeed(symbols=symbols, quote_stale_ms=quote_stale_ms)
    features = FeatureEngine(history_size=180)
    strategies = StrategyStack()
    decision_engine = DecisionEngineV2()
    risk_engine = RiskEngineV2()
    execution_engine = PaperExecutionEngineV2(base_balance_usdt=base_balance)
    exit_engine = ExitEngineV2()
    close_poller = _CloseRequestPoller(_sqlite_path_from_database_url())
    immediate_adverse_shadow_tracker = ImmediateAdverseShadowTracker()
    post_signal_tracker = (
        PostSignalTrajectoryTracker() if post_signal_trajectory_enabled else None
    )
    shadow_risk_candidate_seen_count = 0
    shadow_candidate_registered_count = 0
    shadow_terminal_outcome_count = 0
    shadow_registration_skipped_count = 0
    shadow_registration_skip_reasons: Counter[str] = Counter()
    shadow_terminal_classifications: Counter[str] = Counter()

    telemetry._emit(
        "runtime_v2_started",
        {
            "symbols": symbols,
            "paper_auto_close_sec": paper_auto_close_sec,
            "take_profit_net_usdt": take_profit_net_usdt,
            "stop_loss_net_usdt": stop_loss_net_usdt,
            "loop_sleep_sec": loop_sleep_sec,
            "quote_stale_ms": quote_stale_ms,
            "fill_mode": execution_engine.fill_mode,
            "dynamic_exit_targets_enabled": bool(use_dynamic_exit_targets),
            "dynamic_exit_tp_expected_mult": float(exit_tp_expected_mult),
            "dynamic_exit_sl_expected_mult": float(exit_sl_expected_mult),
            "dynamic_exit_tp_min_usdt": float(exit_tp_min_usdt),
            "dynamic_exit_sl_min_usdt": float(exit_sl_min_usdt),
            "dynamic_exit_horizon_mult": float(exit_horizon_mult),
            "dynamic_exit_min_hold_sec": float(exit_min_hold_sec),
            "explicit_side_allowlist_active": bool(explicit_side_allowlist),
            "explicit_side_allowlist_size": int(len(explicit_side_allowlist)),
            "require_explicit_side_allowlist": bool(require_explicit_side_allowlist),
            "calibration_gate_enabled": bool(calibration_gate_enabled),
            "calibration_gate_fail_closed": bool(calibration_gate_fail_closed),
            "calibration_gate_profile_loaded": bool(
                expected_move_calibration_profile.get("loaded")
            ),
            "calibration_gate_profile_path": expected_move_calibration_profile.get(
                "source_path"
            ),
            "post_signal_trajectory_enabled": bool(post_signal_trajectory_enabled),
            "immediate_adverse_guard_env_enabled": _env_flag(
                "V2_PAPER_IMMEDIATE_ADVERSE_GUARD_ENABLE", "0"
            ),
            "immediate_adverse_guard_profile_blocklist": os.environ.get(
                "V2_PAPER_IMMEDIATE_ADVERSE_GUARD_PROFILE_BLOCKLIST"
            ),
            "shadow_verified_guard_env_enabled": _env_flag(
                "V2_PAPER_SHADOW_VERIFIED_ADVERSE_GUARD_ENABLE", "0"
            ),
            "shadow_verified_guard_rule_id": (
                "SOLUSDTM_buy_TrendFollowingV2_shadow_verified_20260606_000500"
            ),
            "shadow_verified_guard_source_artifact": (
                "analysis/immediate_adverse_shadow_verified_guard_candidates_long_shadow_current.json"
            ),
            **admission_reachability_profile_payload(
                default_v2_min_expected_net_ratio=(
                    decision_engine.default_min_expected_net_ratio
                ),
                default_entry_min_net_usdt=risk_engine.default_entry_min_net_usdt,
                default_v2_min_profile_samples=features._default_min_profile_samples,
            ),
        },
    )

    last_equity_emit_ts = 0.0
    close_mode = False
    cycle_count = 0

    while True:
        now_ts = time.time()
        if now_ts >= run_end_ts:
            close_mode = True
        cycle_count += 1

        quote_by_symbol = feed.fetch_ticks()
        for shadow_payload in immediate_adverse_shadow_tracker.observe_quotes(
            quote_by_symbol,
            now_ts=now_ts,
        ):
            shadow_terminal_outcome_count += 1
            shadow_terminal_classifications[
                str(
                    shadow_payload.get("terminal_classification")
                    or shadow_payload.get("shadow_outcome_classification")
                    or "UNKNOWN"
                )
            ] += 1
            telemetry.emit_immediate_adverse_shadow_outcome(shadow_payload)

        for request in close_poller.poll():
            symbol = str(request.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            position = execution_engine.get_position(symbol)
            if position is None:
                continue
            quote = quote_by_symbol.get(symbol)
            if quote is None:
                continue
            close_payload = execution_engine.close_position(
                symbol=symbol,
                quote=quote,
                now_ts=now_ts,
                reason_code=str(request.get("reason") or "position_close_request"),
            )
            if close_payload is None:
                continue
            decision_engine.register_trade_result(
                symbol=close_payload["symbol"],
                strategy=close_payload.get("strategy") or "",
                side=close_payload.get("side") or "",
                net_pnl=float(close_payload.get("realized_pnl") or 0.0),
            )
            telemetry.emit_position_close(close_payload)

        for symbol in symbols:
            quote = quote_by_symbol.get(symbol)
            if quote is None:
                telemetry.emit_gate_summary(
                    symbol=symbol,
                    reason_code="no_runtime_profile",
                    final_allow=False,
                    candidate=None,
                )
                telemetry.emit_entry_reject(
                    symbol=symbol,
                    reason_code="no_runtime_profile",
                    candidate=None,
                    risk_fields={},
                )
                telemetry.emit_pre_entry_rejection_trace(
                    symbol=symbol,
                    reason_code="no_runtime_profile",
                    candidate=None,
                )
                telemetry.emit_decision(
                    "hold",
                    {"symbol": symbol, "reason_code": "no_runtime_profile"},
                )
                continue

            position = execution_engine.get_position(symbol)
            if position is not None:
                close_decision = exit_engine.evaluate(
                    execution_engine=execution_engine,
                    position=position,
                    quote=quote,
                    now_ts=now_ts,
                )
                telemetry.emit_exit_eval(
                    {
                        "symbol": symbol,
                        "position_id": position.position_id,
                        "reason_code": close_decision.reason_code,
                        "should_close": bool(close_decision.should_close),
                        "age_sec": close_decision.age_sec,
                        "unrealized_gross_pnl": close_decision.unrealized_gross_pnl,
                        "unrealized_net_pnl": close_decision.unrealized_net_pnl,
                    }
                )
                if close_decision.should_close or close_mode:
                    reason_code = (
                        close_decision.reason_code
                        if close_decision.should_close
                        else "run_end"
                    )
                    close_payload = execution_engine.close_position(
                        symbol=symbol,
                        quote=quote,
                        now_ts=now_ts,
                        reason_code=reason_code,
                    )
                    if close_payload is not None:
                        decision_engine.register_trade_result(
                            symbol=close_payload["symbol"],
                            strategy=close_payload.get("strategy") or "",
                            side=close_payload.get("side") or "",
                            net_pnl=float(close_payload.get("realized_pnl") or 0.0),
                        )
                        telemetry.emit_position_close(close_payload)
                else:
                    telemetry.emit_gate_summary(
                        symbol=symbol,
                        reason_code="current_side",
                        final_allow=False,
                        candidate=None,
                    )
                    telemetry.emit_entry_reject(
                        symbol=symbol,
                        reason_code="current_side",
                        candidate=None,
                        risk_fields={"position_id": position.position_id},
                    )
                    telemetry.emit_pre_entry_rejection_trace(
                        symbol=symbol,
                        reason_code="current_side",
                        candidate=None,
                    )
                    telemetry.emit_decision(
                        "hold",
                        {"symbol": symbol, "reason_code": "current_side"},
                    )
                continue

            if close_mode:
                telemetry.emit_gate_summary(
                    symbol=symbol,
                    reason_code="net_target_guard",
                    final_allow=False,
                    candidate=None,
                )
                telemetry.emit_entry_reject(
                    symbol=symbol,
                    reason_code="net_target_guard",
                    candidate=None,
                    risk_fields={},
                )
                telemetry.emit_pre_entry_rejection_trace(
                    symbol=symbol,
                    reason_code="net_target_guard",
                    candidate=None,
                )
                telemetry.emit_decision(
                    "hold",
                    {"symbol": symbol, "reason_code": "net_target_guard"},
                )
                continue

            if post_signal_tracker is not None:
                for trajectory_payload in post_signal_tracker.observe_quote(quote):
                    telemetry._emit("post_signal_trajectory_v2", trajectory_payload)

            feature = features.ingest(quote)
            signals = strategies.evaluate(feature)
            directional_signals = [
                signal
                for signal in signals
                if str(signal.direction).lower() in {"buy", "sell"}
            ]
            if explicit_side_allowlist:
                allowlisted_signals = [
                    signal
                    for signal in directional_signals
                    if _is_allowlisted_signal(
                        symbol=symbol,
                        strategy=signal.strategy,
                        side=signal.direction,
                        allowlist=explicit_side_allowlist,
                    )
                ]
                selected_allowlisted_signals = allowlisted_signals
                if not allowlisted_signals:
                    if diagnostic_force_open:
                        synthetic_signals: list[StrategySignal] = []
                        for token in sorted(explicit_side_allowlist):
                            parts = str(token).split(":")
                            if len(parts) != 3:
                                continue
                            allow_symbol, allow_strategy, allow_side = parts
                            if str(allow_symbol).strip().upper() != symbol:
                                continue
                            if str(allow_side).strip().lower() not in {"buy", "sell"}:
                                continue
                            synthetic_signals.append(
                                StrategySignal(
                                    strategy=_strategy_name_from_allowlist_key(
                                        allow_strategy
                                    ),
                                    direction=str(allow_side).strip().lower(),
                                    score=1.0,
                                    confidence=1.0,
                                    expected_move=max(
                                        0.0,
                                        _env_float(
                                            "DIAGNOSTIC_FORCE_OPEN_EXPECTED_MOVE",
                                            0.003,
                                        ),
                                    ),
                                    reason_code="diagnostic_force_open",
                                    metadata={
                                        "diagnostic_force_open": True,
                                        "source": "explicit_side_allowlist",
                                    },
                                )
                            )
                        if synthetic_signals:
                            selected_allowlisted_signals = synthetic_signals
                        else:
                            telemetry.emit_gate_summary(
                                symbol=symbol,
                                reason_code="symbol_strategy_side_allowlist",
                                final_allow=False,
                                candidate=None,
                            )
                            telemetry.emit_entry_reject(
                                symbol=symbol,
                                reason_code="symbol_strategy_side_allowlist",
                                candidate=None,
                                risk_fields={"allowlist_active": True},
                            )
                            telemetry.emit_pre_entry_rejection_trace(
                                symbol=symbol,
                                reason_code="symbol_strategy_side_allowlist",
                                candidate=None,
                            )
                            telemetry.emit_decision(
                                "hold",
                                {
                                    "symbol": symbol,
                                    "reason_code": "symbol_strategy_side_allowlist",
                                },
                            )
                            continue
                    else:
                        telemetry.emit_gate_summary(
                            symbol=symbol,
                            reason_code="symbol_strategy_side_allowlist",
                            final_allow=False,
                            candidate=None,
                        )
                        telemetry.emit_entry_reject(
                            symbol=symbol,
                            reason_code="symbol_strategy_side_allowlist",
                            candidate=None,
                            risk_fields={"allowlist_active": True},
                        )
                        telemetry.emit_pre_entry_rejection_trace(
                            symbol=symbol,
                            reason_code="symbol_strategy_side_allowlist",
                            candidate=None,
                        )
                        telemetry.emit_decision(
                            "hold",
                            {
                                "symbol": symbol,
                                "reason_code": "symbol_strategy_side_allowlist",
                            },
                        )
                        continue
                signals = selected_allowlisted_signals
            all_candidates, best_candidate, selection_reason = decision_engine.evaluate(
                quote=quote,
                feature=feature,
                signals=signals,
            )
            if post_signal_tracker is not None:
                post_signal_tracker.observe_candidates(
                    symbol=symbol,
                    candidates=all_candidates[:3],
                    reason_code=selection_reason,
                    contamination_flags={
                        "seed": 0,
                        "fallback": 0,
                        "mock": 0,
                        "force_open": int(bool(diagnostic_force_open)),
                        "forced_cycle": 0,
                    },
                )
            for candidate in all_candidates[:3]:
                telemetry.emit_entry_eval(
                    symbol=symbol,
                    candidate=candidate,
                    final_allow=False,
                    reason_code=selection_reason,
                )

            if best_candidate is None:
                candidate_ref = all_candidates[0] if all_candidates else None
                telemetry.emit_gate_summary(
                    symbol=symbol,
                    reason_code=selection_reason,
                    final_allow=False,
                    candidate=candidate_ref,
                )
                telemetry.emit_entry_reject(
                    symbol=symbol,
                    reason_code=selection_reason,
                    candidate=candidate_ref,
                    risk_fields={},
                )
                telemetry.emit_pre_entry_rejection_trace(
                    symbol=symbol,
                    reason_code=selection_reason,
                    candidate=candidate_ref,
                )
                telemetry.emit_decision(
                    "hold",
                    {"symbol": symbol, "reason_code": selection_reason},
                )
                continue

            telemetry.emit_entry_eval(
                symbol=symbol,
                candidate=best_candidate,
                final_allow=True,
                reason_code="allow",
            )
            shadow_risk_candidate_seen_count += 1
            plan = risk_engine.build_order_plan(
                candidate=best_candidate,
                free_equity_usdt=execution_engine.mark_to_market(
                    {k: v for k, v in quote_by_symbol.items() if v is not None}
                ),
                open_positions_count=len(execution_engine.positions),
            )
            immediate_adverse_guard_fields = {
                key: value
                for key, value in dict(plan.sizing_trace).items()
                if key.startswith("immediate_adverse_guard_")
                or key
                in {
                    "symbol",
                    "side",
                    "strategy",
                    "expected_net",
                    "probability",
                    "risk_score",
                    "guard_threshold",
                    "historical_immediate_adverse_rate",
                    "historical_tail_loss_net",
                }
            }
            if immediate_adverse_guard_fields:
                telemetry.emit_immediate_adverse_guard(
                    status=(
                        "blocked"
                        if plan.reason_code == "entry_immediate_adverse_guard"
                        else "allowed"
                    ),
                    fields=immediate_adverse_guard_fields,
                )
            shadow_verified_guard_fields = _shadow_verified_guard_fields_from_trace(
                dict(plan.sizing_trace)
            )
            if shadow_verified_guard_fields:
                telemetry.emit_shadow_verified_guard(
                    status=(
                        "blocked"
                        if plan.reason_code
                        == "entry_shadow_verified_immediate_adverse_guard"
                        else "allowed"
                    ),
                    fields=shadow_verified_guard_fields,
                )
            shadow_registration_fields = {}
            shadow_registration_fields.update(immediate_adverse_guard_fields)
            shadow_registration_fields.update(shadow_verified_guard_fields)
            should_register_shadow_candidate = (
                plan.reason_code
                in {
                    "entry_immediate_adverse_guard",
                    "entry_shadow_verified_immediate_adverse_guard",
                }
                or bool(
                    immediate_adverse_guard_fields.get(
                        "immediate_adverse_guard_shadow_candidate"
                    )
                )
                or bool(
                    shadow_verified_guard_fields.get("shadow_verified_guard_blocked")
                )
            )
            if should_register_shadow_candidate:
                immediate_adverse_shadow_tracker.add_blocked_candidate(
                    symbol=best_candidate.symbol,
                    side=best_candidate.side,
                    strategy=best_candidate.strategy,
                    opened_ts=now_ts,
                    entry_price=float(quote.mid),
                    quantity_base=max(0.0, float(plan.quantity_base)),
                    fee_rate=float(plan.fee_rate),
                    take_profit_net_usdt=float(
                        plan.sizing_trace.get("estimated_take_profit_net_usdt")
                        or take_profit_net_usdt
                    ),
                    stop_loss_net_usdt=float(
                        plan.sizing_trace.get("estimated_stop_loss_net_usdt")
                        or stop_loss_net_usdt
                    ),
                    max_hold_sec=float(paper_auto_close_sec),
                    guard_fields=dict(shadow_registration_fields),
                )
                shadow_candidate_registered_count += 1
            elif immediate_adverse_guard_fields or shadow_verified_guard_fields:
                shadow_registration_skipped_count += 1
                shadow_registration_skip_reasons["guard_not_shadow_candidate"] += 1
            else:
                shadow_registration_skipped_count += 1
                shadow_registration_skip_reasons["guard_not_evaluated"] += 1
            if not plan.accepted:
                telemetry.emit_gate_summary(
                    symbol=symbol,
                    reason_code=plan.reason_code,
                    final_allow=False,
                    candidate=best_candidate,
                )
                telemetry.emit_entry_reject(
                    symbol=symbol,
                    reason_code=plan.reason_code,
                    candidate=best_candidate,
                    risk_fields={"sizing_trace": dict(plan.sizing_trace)},
                )
                telemetry.emit_pre_entry_rejection_trace(
                    symbol=symbol,
                    reason_code=plan.reason_code,
                    candidate=best_candidate,
                )
                telemetry.emit_decision(
                    "hold",
                    {
                        "symbol": symbol,
                        "reason_code": plan.reason_code,
                        "expected_net_after_full_cost": (
                            plan.expected_net_after_full_cost
                        ),
                    },
                )
                continue

            signal_horizon_ticks = _safe_float(
                plan.signal_metadata.get("signal_horizon_ticks")
            )
            if signal_horizon_ticks is None:
                signal_horizon_ticks = _safe_float(
                    plan.cost_breakdown.get("signal_horizon_ticks")
                )
            exit_controls = _derive_exit_controls(
                base_take_profit_net_usdt=take_profit_net_usdt,
                base_stop_loss_net_usdt=stop_loss_net_usdt,
                base_max_hold_sec=float(paper_auto_close_sec),
                expected_net_after_full_cost_usdt=float(
                    plan.expected_net_after_full_cost
                ),
                signal_horizon_ticks=signal_horizon_ticks,
                loop_sleep_sec=float(loop_sleep_sec),
                use_expected_targets=bool(use_dynamic_exit_targets),
                tp_expected_mult=float(exit_tp_expected_mult),
                sl_expected_mult=float(exit_sl_expected_mult),
                tp_min_usdt=float(exit_tp_min_usdt),
                sl_min_usdt=float(exit_sl_min_usdt),
                horizon_mult=float(exit_horizon_mult),
                min_hold_sec=float(exit_min_hold_sec),
            )
            applied_take_profit_net_usdt = float(
                exit_controls.get("take_profit_net_usdt") or take_profit_net_usdt
            )
            applied_stop_loss_net_usdt = float(
                exit_controls.get("stop_loss_net_usdt") or stop_loss_net_usdt
            )
            execution_horizon_sec = float(
                exit_controls.get("execution_horizon_sec")
                or float(paper_auto_close_sec)
            )
            signal_horizon_sec_estimate = exit_controls.get(
                "signal_horizon_sec_estimate"
            )
            time_horizon_mismatch_sec = exit_controls.get("time_horizon_mismatch_sec")
            time_horizon_mismatch_ratio = exit_controls.get(
                "time_horizon_mismatch_ratio"
            )

            calibration_gate = evaluate_expected_move_calibration_gate(
                enabled=bool(calibration_gate_enabled),
                fail_closed=bool(calibration_gate_fail_closed),
                profile=expected_move_calibration_profile,
                symbol=best_candidate.symbol,
                strategy=best_candidate.strategy,
                side=best_candidate.side,
                expected_gross_before_cost=plan.signal_metadata.get(
                    "expected_gross_before_cost",
                    plan.expected_move,
                ),
                expected_cost_usdt=(
                    _safe_float(plan.cost_breakdown.get("total_cost_ratio")) or 0.0
                )
                * float(plan.final_notional_usdt),
                expected_notional_usdt=float(plan.final_notional_usdt),
                signal_horizon_sec_estimate=signal_horizon_sec_estimate,
                time_horizon_mismatch_ratio=time_horizon_mismatch_ratio,
                min_sample=calibration_gate_min_sample,
                min_positive_net_share=calibration_gate_min_positive_net_share,
                min_calibrated_expected_net=calibration_gate_min_expected_net,
                max_mismatch_ratio=calibration_gate_max_mismatch_ratio,
            )
            if not bool(calibration_gate.get("allow")):
                reason_code = str(
                    calibration_gate.get("reason_code") or "calibration_gate"
                )
                telemetry.emit_gate_summary(
                    symbol=symbol,
                    reason_code=reason_code,
                    final_allow=False,
                    candidate=best_candidate,
                )
                telemetry.emit_entry_reject(
                    symbol=symbol,
                    reason_code=reason_code,
                    candidate=best_candidate,
                    risk_fields={"calibration_gate": dict(calibration_gate)},
                )
                telemetry.emit_pre_entry_rejection_trace(
                    symbol=symbol,
                    reason_code=reason_code,
                    candidate=best_candidate,
                )
                telemetry.emit_decision(
                    "hold",
                    {
                        "symbol": symbol,
                        "reason_code": reason_code,
                        "calibration_gate": dict(calibration_gate),
                    },
                )
                continue
            position = execution_engine.open_position(
                plan=plan,
                quote=quote,
                now_ts=now_ts,
                take_profit_net_usdt=applied_take_profit_net_usdt,
                stop_loss_net_usdt=applied_stop_loss_net_usdt,
                max_hold_sec=execution_horizon_sec,
            )
            position.take_profit_net_usdt = applied_take_profit_net_usdt
            position.stop_loss_net_usdt = applied_stop_loss_net_usdt
            position.max_hold_sec = execution_horizon_sec

            position.meta["runtime_profile_source"] = plan.cost_breakdown.get(
                "runtime_profile_source"
            )
            position.meta["runtime_profile_key"] = plan.cost_breakdown.get(
                "runtime_profile_key"
            )
            position.meta["runtime_profile_age_sec"] = plan.cost_breakdown.get(
                "runtime_profile_age_sec"
            )
            position.meta["runtime_profile_span_sec"] = plan.cost_breakdown.get(
                "runtime_profile_span_sec"
            )
            position.meta["runtime_profile_sample_size"] = plan.cost_breakdown.get(
                "runtime_profile_sample_size"
            )
            position.meta["signal_confidence_scaling"] = dict(
                plan.signal_metadata.get("confidence_scaling") or {}
            )
            position.meta["signal_expected_move_formula"] = plan.signal_metadata.get(
                "expected_move_formula"
            )
            expected_move_scaled = plan.signal_metadata.get(
                "expected_move_scaled",
                plan.expected_move,
            )
            position.meta["expected_move_raw"] = plan.signal_metadata.get(
                "expected_move_raw",
                expected_move_scaled,
            )
            position.meta["expected_move_scaled"] = expected_move_scaled
            position.meta["expected_gross_before_cost"] = plan.signal_metadata.get(
                "expected_gross_before_cost",
                expected_move_scaled,
            )
            position.meta["signal_horizon_ticks"] = signal_horizon_ticks
            position.meta["signal_horizon_sec_estimate"] = signal_horizon_sec_estimate
            position.meta["execution_horizon_sec"] = execution_horizon_sec
            position.meta["time_decay_exit_sec"] = execution_horizon_sec
            position.meta["take_profit_net_usdt"] = applied_take_profit_net_usdt
            position.meta["stop_loss_net_usdt"] = applied_stop_loss_net_usdt
            position.meta["time_horizon_mismatch_sec"] = time_horizon_mismatch_sec
            position.meta["time_horizon_mismatch_ratio"] = time_horizon_mismatch_ratio
            position.meta["calibration_gate"] = dict(calibration_gate)
            position.meta["tuple_concentration"] = plan.cost_breakdown.get(
                "tuple_concentration"
            )
            position.meta["trendfollowing_tuple_concentration"] = (
                plan.cost_breakdown.get("trendfollowing_tuple_concentration")
            )
            position.meta["expected_cost_ratio"] = plan.cost_breakdown.get(
                "total_cost_ratio"
            )
            position.meta["expected_cost_usdt"] = (
                _safe_float(plan.cost_breakdown.get("total_cost_ratio")) or 0.0
            ) * float(plan.final_notional_usdt)

            telemetry.emit_gate_summary(
                symbol=symbol,
                reason_code="allow",
                final_allow=True,
                candidate=best_candidate,
            )
            open_payload = _position_payload(
                position,
                quote.mid,
                extra_meta={
                    "runtime_profile_source": position.meta.get(
                        "runtime_profile_source"
                    ),
                    "runtime_profile_key": position.meta.get("runtime_profile_key"),
                    "runtime_profile_age_sec": position.meta.get(
                        "runtime_profile_age_sec"
                    ),
                    "runtime_profile_span_sec": position.meta.get(
                        "runtime_profile_span_sec"
                    ),
                    "runtime_profile_sample_size": position.meta.get(
                        "runtime_profile_sample_size"
                    ),
                    "expected_move_raw": position.meta.get("expected_move_raw"),
                    "expected_move_scaled": position.meta.get("expected_move_scaled"),
                    "expected_gross_before_cost": position.meta.get(
                        "expected_gross_before_cost"
                    ),
                    "signal_horizon_ticks": position.meta.get("signal_horizon_ticks"),
                    "signal_horizon_sec_estimate": position.meta.get(
                        "signal_horizon_sec_estimate"
                    ),
                    "take_profit_net_usdt": position.meta.get("take_profit_net_usdt"),
                    "stop_loss_net_usdt": position.meta.get("stop_loss_net_usdt"),
                    "execution_horizon_sec": position.meta.get("execution_horizon_sec"),
                    "time_decay_exit_sec": position.meta.get("time_decay_exit_sec"),
                    "time_horizon_mismatch_sec": position.meta.get(
                        "time_horizon_mismatch_sec"
                    ),
                    "time_horizon_mismatch_ratio": position.meta.get(
                        "time_horizon_mismatch_ratio"
                    ),
                    "signal_confidence_scaling": position.meta.get(
                        "signal_confidence_scaling"
                    ),
                    "signal_expected_move_formula": position.meta.get(
                        "signal_expected_move_formula"
                    ),
                    "tuple_concentration": position.meta.get("tuple_concentration"),
                    "trendfollowing_tuple_concentration": position.meta.get(
                        "trendfollowing_tuple_concentration"
                    ),
                    "expected_cost_ratio": position.meta.get("expected_cost_ratio"),
                    "expected_cost_usdt": position.meta.get("expected_cost_usdt"),
                },
            )
            telemetry.emit_position_open(plan=plan, position_payload=open_payload)
            telemetry.emit_decision(
                position.side,
                {
                    "symbol": symbol,
                    "strategy": position.strategy,
                    "reason_code": "allow",
                    "expected_net_after_full_cost": plan.expected_net_after_full_cost,
                },
            )

        if (now_ts - last_equity_emit_ts) >= float(equity_snapshot_sec):
            equity = execution_engine.mark_to_market(
                {k: v for k, v in quote_by_symbol.items() if v is not None}
            )
            telemetry.emit_equity(
                equity=equity,
                pnl=(equity - execution_engine.base_balance_usdt),
            )
            last_equity_emit_ts = now_ts

        if close_mode and not execution_engine.positions:
            break

        if paper_run_once and cycle_count >= 1:
            close_mode = True
            if not execution_engine.positions:
                break

        time.sleep(loop_sleep_sec)

    # Final forced close pass to fail-closed lifecycle.
    for shadow_payload in immediate_adverse_shadow_tracker.flush_expired(
        {k: v for k, v in feed.fetch_ticks().items() if v is not None},
        now_ts=time.time(),
        shutdown=True,
    ):
        shadow_terminal_outcome_count += 1
        shadow_terminal_classifications[
            str(
                shadow_payload.get("terminal_classification")
                or shadow_payload.get("shadow_outcome_classification")
                or "UNKNOWN"
            )
        ] += 1
        telemetry.emit_immediate_adverse_shadow_outcome(shadow_payload)
    if execution_engine.positions:
        final_quotes = feed.fetch_ticks()
        now_ts = time.time()
        for symbol in list(execution_engine.positions.keys()):
            quote = final_quotes.get(symbol)
            if quote is None:
                continue
            close_payload = execution_engine.close_position(
                symbol=symbol,
                quote=quote,
                now_ts=now_ts,
                reason_code="run_end",
            )
            if close_payload is not None:
                decision_engine.register_trade_result(
                    symbol=close_payload["symbol"],
                    strategy=close_payload.get("strategy") or "",
                    side=close_payload.get("side") or "",
                    net_pnl=float(close_payload.get("realized_pnl") or 0.0),
                )
                telemetry.emit_position_close(close_payload)
    final_equity = (
        execution_engine.base_balance_usdt + execution_engine.realized_pnl_usdt
    )
    telemetry.emit_equity(
        equity=final_equity,
        pnl=(final_equity - execution_engine.base_balance_usdt),
    )
    telemetry._emit(
        "runtime_v2_stopped",
        {
            "realized_pnl_usdt": execution_engine.realized_pnl_usdt,
            "final_equity_usdt": final_equity,
            "cycle_count": cycle_count,
            **_shadow_reachability_payload(
                risk_candidate_seen_count=shadow_risk_candidate_seen_count,
                shadow_candidate_registered_count=shadow_candidate_registered_count,
                shadow_terminal_outcome_count=shadow_terminal_outcome_count,
                shadow_registration_skipped_count=shadow_registration_skipped_count,
                shadow_registration_skip_reasons=dict(shadow_registration_skip_reasons),
                shadow_terminal_classifications=dict(shadow_terminal_classifications),
            ),
        },
    )
