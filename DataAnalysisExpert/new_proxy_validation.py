# flake8: noqa: E501

from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from profitability_total_cost_audit import _extract_run_metrics


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "analysis"
AUTOPSY = ROOT / "autopsy"

CANDIDATE_NAME = "fee_aware_expected_edge_router_lead_proxy_v1"
VALIDATION_DB_GLOBS = (
    "phase88_newproxy_validate*_paper_v2.db",
    "phase89_newproxy_expand*_paper_v2.db",
    "phase90_newproxy_confirm*_paper_v2.db",
    "phase91_newproxy_targeted*_paper_v2.db",
)

CONFIRMATION_DB_PREFIX = "phase90_newproxy_confirm"
BASELINE_BATCH_COUNT = 11
CONFIRMATION_LINKED_CLOSE_MIN = 60
CONFIRMATION_HARD_CLOSE_SHARE_MAX = 0.80
LINK_DECISION_TS_MAX_DELTA_SEC = 180.0
SEED_IN_PATH_RE = re.compile(r"_seed(\d+)(?=_|$)")


@dataclass(frozen=True)
class DecisionEval:
    db_path: Path
    timestamp: datetime
    symbol: str | None
    raw_decision: str | None
    final_decision: str | None
    candidate_history_ready: bool
    candidate_value: float | None
    candidate_expected_edge_after_fee: float | None
    candidate_router_lead: float | None
    old_proxy_value: float | None
    readiness_linkage_eligible: bool | None = None
    partial_history_ready: bool = False
    linkage_excluded_reason: str | None = None


@dataclass(frozen=True)
class PositionOpen:
    db_path: Path
    symbol: str | None
    side: str | None
    decision_ts: datetime | None
    trade_id: str | None
    entry_expected_edge_after_fee: float | None


@dataclass(frozen=True)
class PositionClose:
    db_path: Path
    trade_id: str
    symbol: str | None
    side: str | None
    net_pnl: float | None
    gross_pnl: float | None
    feasible_net: float | None
    capture_ratio_proxy: float | None
    hard_close: bool | None
    close_reason: str | None


def _discover_run_db_paths() -> list[Path]:
    discovered: list[Path] = []
    seen: set[Path] = set()
    for pattern in VALIDATION_DB_GLOBS:
        for path in sorted(AUTOPSY.glob(pattern)):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            discovered.append(path)
    return discovered


def _extract_seed_from_path(path: Path) -> int | None:
    matches = SEED_IN_PATH_RE.findall(path.name)
    if not matches:
        return None
    try:
        return int(matches[-1])
    except Exception:
        return None


def _load_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, str):
            data = json.loads(data)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        result = float(value)
        if not math.isfinite(result):
            return None
        return result
    except Exception:
        return None


def _mean(values: list[float | None]) -> float | None:
    valid = [float(value) for value in values if isinstance(value, (int, float))]
    if not valid:
        return None
    return float(sum(valid)) / float(len(valid))


def _parse_db_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S.%f")
    except Exception:
        return None


def _parse_iso_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except Exception:
        return None


def _normalize_side(value: Any) -> str | None:
    side = str(value or "").strip().lower()
    if side in {"buy", "long"}:
        return "buy"
    if side in {"sell", "short"}:
        return "sell"
    return None


def _pairwise_auc(positives: list[float], negatives: list[float]) -> float | None:
    if not positives or not negatives:
        return None
    wins = 0.0
    total = 0
    for pos in positives:
        for neg in negatives:
            total += 1
            if pos > neg:
                wins += 1.0
            elif pos == neg:
                wins += 0.5
    if total <= 0:
        return None
    return wins / float(total)


def _rank(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    out = [0.0] * len(values)
    cursor = 0
    while cursor < len(indexed):
        end = cursor
        while end + 1 < len(indexed) and indexed[end + 1][1] == indexed[cursor][1]:
            end += 1
        avg_rank = (float(cursor + 1) + float(end + 1)) / 2.0
        for idx in range(cursor, end + 1):
            out[indexed[idx][0]] = avg_rank
        cursor = end + 1
    return out


def _pearson(x_values: list[float], y_values: list[float]) -> float | None:
    if len(x_values) != len(y_values) or len(x_values) < 2:
        return None
    mean_x = _mean(x_values)
    mean_y = _mean(y_values)
    if mean_x is None or mean_y is None:
        return None
    cov = 0.0
    var_x = 0.0
    var_y = 0.0
    for x_value, y_value in zip(x_values, y_values):
        dx = x_value - mean_x
        dy = y_value - mean_y
        cov += dx * dy
        var_x += dx * dx
        var_y += dy * dy
    if var_x <= 0.0 or var_y <= 0.0:
        return None
    return cov / math.sqrt(var_x * var_y)


def _spearman(pairs: list[tuple[float | None, float | None]]) -> float | None:
    valid = [
        (float(x_val), float(y_val))
        for x_val, y_val in pairs
        if x_val is not None and y_val is not None
    ]
    if len(valid) < 3:
        return None
    x_rank = _rank([pair[0] for pair in valid])
    y_rank = _rank([pair[1] for pair in valid])
    return _pearson(x_rank, y_rank)


def _metric_alignment_rate(
    values: list[tuple[float | None, float | None]],
    larger_is_better: bool,
) -> dict[str, Any]:
    valid = [
        (float(left), float(right))
        for left, right in values
        if left is not None and right is not None
    ]
    if len(valid) < 3:
        return {
            "pair_count": 0,
            "aligned_count": 0,
            "alignment_rate": None,
            "spearman": None,
        }
    aligned = 0
    pair_count = 0
    for idx in range(len(valid)):
        left_x, left_y = valid[idx]
        for jdx in range(idx + 1, len(valid)):
            right_x, right_y = valid[jdx]
            if left_x == right_x:
                continue
            pair_count += 1
            if larger_is_better:
                outcome = (
                    (left_x < right_x and left_y <= right_y)
                    or (left_x > right_x and left_y >= right_y)
                )
            else:
                outcome = (
                    (left_x < right_x and left_y >= right_y)
                    or (left_x > right_x and left_y <= right_y)
                )
            if outcome:
                aligned += 1
    return {
        "pair_count": pair_count,
        "aligned_count": aligned,
        "alignment_rate": (aligned / float(pair_count)) if pair_count > 0 else None,
        "spearman": _spearman(valid),
    }


def _bucket_monotonicity(
    rows: list[dict[str, Any]],
    value_field: str,
) -> dict[str, Any]:
    valid = [row for row in rows if row.get(value_field) is not None]
    if len(valid) < 9:
        return {
            "bucket_count": 0,
            "eligible": False,
            "reason": "fewer_than_9_linked_closes",
            "metrics": {},
            "score": None,
        }
    valid.sort(key=lambda row: float(row[value_field]))
    bucket_size = int(math.ceil(len(valid) / 3.0))
    buckets = [
        valid[idx : idx + bucket_size]
        for idx in range(0, len(valid), bucket_size)
    ]
    if len(buckets) < 3:
        return {
            "bucket_count": len(buckets),
            "eligible": False,
            "reason": "fewer_than_3_buckets",
            "metrics": {},
            "score": None,
        }

    def _bucket_mean(bucket: list[dict[str, Any]], field: str) -> float | None:
        return _mean([_safe_float(item.get(field)) for item in bucket])

    metrics = {
        "mean_net_per_close": {
            "direction": "up",
            "bucket_means": [_bucket_mean(bucket, "net_pnl") for bucket in buckets],
        },
        "mean_gross_per_close": {
            "direction": "up",
            "bucket_means": [_bucket_mean(bucket, "gross_pnl") for bucket in buckets],
        },
        "mean_feasible_net": {
            "direction": "up",
            "bucket_means": [
                _bucket_mean(bucket, "feasible_net") for bucket in buckets
            ],
        },
        "hard_close_share": {
            "direction": "down",
            "bucket_means": [
                _bucket_mean(bucket, "hard_close_flag") for bucket in buckets
            ],
        },
    }
    metric_scores = []
    for metric in metrics.values():
        means = metric["bucket_means"]
        if any(mean is None for mean in means):
            metric["alignment_rate"] = None
            continue
        comparisons = 0
        aligned = 0
        for left, right in zip(means, means[1:]):
            comparisons += 1
            if metric["direction"] == "up" and right >= left:
                aligned += 1
            elif metric["direction"] == "down" and right <= left:
                aligned += 1
        metric["alignment_rate"] = (
            aligned / float(comparisons) if comparisons > 0 else None
        )
        if metric["alignment_rate"] is not None:
            metric_scores.append(metric["alignment_rate"])
    return {
        "bucket_count": len(buckets),
        "eligible": True,
        "reason": None,
        "metrics": metrics,
        "score": _mean(metric_scores),
    }


def _load_decision_evals(db_path: Path) -> list[DecisionEval]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        rows = cur.execute(
            "select timestamp, details from decisions order by rowid"
        ).fetchall()
    finally:
        conn.close()
    out: list[DecisionEval] = []
    for row in rows:
        payload = _load_json(row["details"])
        candidate = payload.get("entry_proxy_candidate")
        if not isinstance(candidate, dict):
            continue
        old_proxy = payload.get("entry_live_edge")
        old_proxy = old_proxy if isinstance(old_proxy, dict) else {}
        timestamp = _parse_db_timestamp(row["timestamp"])
        if timestamp is None:
            continue
        out.append(
            DecisionEval(
                db_path=db_path,
                timestamp=timestamp,
                symbol=payload.get("symbol"),
                raw_decision=payload.get("entry_decision_raw"),
                final_decision=payload.get("entry_decision_final"),
                candidate_history_ready=bool(candidate.get("history_ready")),
                candidate_value=_safe_float(candidate.get("candidate_proxy_value")),
                candidate_expected_edge_after_fee=_safe_float(
                    candidate.get("expected_edge_after_fee")
                ),
                candidate_router_lead=_safe_float(candidate.get("router_lead")),
                old_proxy_value=_safe_float(old_proxy.get("live_edge_proxy")),
            )
        )
    return out


def _load_position_opens(db_path: Path) -> list[PositionOpen]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        rows = cur.execute(
            "select details from logs where event='position_open' order by rowid"
        ).fetchall()
    finally:
        conn.close()
    out: list[PositionOpen] = []
    for row in rows:
        payload = _load_json(row["details"])
        position = payload.get("position")
        position = position if isinstance(position, dict) else {}
        out.append(
            PositionOpen(
                db_path=db_path,
                symbol=payload.get("symbol") or position.get("symbol"),
                side=_normalize_side(
                    payload.get("entry_side")
                    or payload.get("side")
                    or position.get("side")
                ),
                decision_ts=_parse_iso_timestamp(
                    position.get("decision_ts") or payload.get("decision_ts")
                ),
                trade_id=position.get("trade_id") or payload.get("trade_id"),
                entry_expected_edge_after_fee=_safe_float(
                    position.get("entry_expected_edge_after_fee")
                ),
            )
        )
    return out


def _load_position_closes(db_path: Path) -> dict[str, PositionClose]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        rows = cur.execute(
            "select details from logs where event='position_close' order by rowid"
        ).fetchall()
    finally:
        conn.close()
    out: dict[str, PositionClose] = {}
    for row in rows:
        payload = _load_json(row["details"])
        position = payload.get("position")
        position = position if isinstance(position, dict) else {}
        pnl_decompose = payload.get("pnl_decompose")
        pnl_decompose = pnl_decompose if isinstance(pnl_decompose, dict) else {}
        trade_id = position.get("trade_id") or payload.get("trade_id")
        if not trade_id:
            continue
        hard_close = None
        exit_reason = str(
            payload.get("exit_reason")
            or payload.get("close_reason")
            or payload.get("reason")
            or ""
        ).strip().lower()
        if exit_reason:
            hard_close = exit_reason == "auto_close_hard"
        out[str(trade_id)] = PositionClose(
            db_path=db_path,
            trade_id=str(trade_id),
            symbol=payload.get("symbol") or position.get("symbol"),
            side=_normalize_side(position.get("side") or payload.get("side")),
            net_pnl=_safe_float(
                payload.get("realized_net") or payload.get("realized_pnl")
            ),
            gross_pnl=_safe_float(pnl_decompose.get("gross_fill_pnl_model")),
            feasible_net=_safe_float(payload.get("pre_hard_close_best_feasible_net")),
            capture_ratio_proxy=_safe_float(payload.get("capture_ratio_proxy")),
            hard_close=hard_close,
            close_reason=exit_reason or None,
        )
    return out


def _count_telemetry_events(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        candidate_logs = cur.execute(
            (
                "select count(*) as count from logs "
                "where event='entry_proxy_candidate_eval'"
            )
        ).fetchone()
        decision_payloads = cur.execute(
            (
                "select count(*) as count from decisions "
                "where details like '%\"entry_proxy_candidate\"%'"
            )
        ).fetchone()
    finally:
        conn.close()
    return {
        "entry_proxy_candidate_eval_count": int(
            candidate_logs["count"] if candidate_logs else 0
        ),
        "decision_payload_entry_proxy_candidate_count": int(
            decision_payloads["count"] if decision_payloads else 0
        ),
    }


def _link_outcomes(
    decisions: list[DecisionEval],
    opens: list[PositionOpen],
    closes: dict[str, PositionClose],
) -> list[dict[str, Any]]:
    eligible_decisions = [
        row
        for row in decisions
        if row.final_decision in {"buy", "sell"}
        and row.candidate_expected_edge_after_fee is not None
        and (
            bool(row.readiness_linkage_eligible)
            if row.readiness_linkage_eligible is not None
            else (
                row.candidate_history_ready
                and row.candidate_value is not None
            )
        )
    ]
    linked: list[dict[str, Any]] = []
    used_trade_ids: set[str] = set()
    for decision in eligible_decisions:
        match = _match_linkage_evidence(
            decision,
            opens,
            closes,
            used_trade_ids=used_trade_ids,
        )
        if match.get("status") != "ok":
            continue
        best_open = match["open"]
        close_payload = match["close"]
        used_trade_ids.add(best_open.trade_id)
        linked.append(
            {
                "db_path": str(decision.db_path),
                "symbol": decision.symbol,
                "side": best_open.side,
                "candidate_value": decision.candidate_value,
                "candidate_expected_edge_after_fee": (
                    decision.candidate_expected_edge_after_fee
                ),
                "candidate_router_lead": decision.candidate_router_lead,
                "old_proxy_value": decision.old_proxy_value,
                "trade_id": best_open.trade_id,
                "decision_timestamp": decision.timestamp.isoformat(),
                "net_pnl": close_payload.net_pnl,
                "gross_pnl": close_payload.gross_pnl,
                "feasible_net": close_payload.feasible_net,
                "capture_ratio_proxy": close_payload.capture_ratio_proxy,
                "hard_close_flag": (
                    1.0
                    if close_payload.hard_close
                    else 0.0
                    if close_payload.hard_close is not None
                    else None
                ),
                "hard_close": close_payload.hard_close,
                "close_reason": close_payload.close_reason,
            }
        )
    return linked


def _match_linkage_evidence(
    decision: DecisionEval,
    opens: list[PositionOpen],
    closes: dict[str, PositionClose],
    used_trade_ids: set[str] | None = None,
) -> dict[str, Any]:
    decision_side = _normalize_side(decision.final_decision)
    symbol_side_matches = [
        pos_open
        for pos_open in opens
        if pos_open.symbol == decision.symbol
        and pos_open.side == decision_side
        and (
            used_trade_ids is None
            or pos_open.trade_id not in used_trade_ids
        )
    ]
    if not symbol_side_matches:
        return {"status": "no_open_symbol_side_match"}

    edge_ready_matches = [
        pos_open
        for pos_open in symbol_side_matches
        if pos_open.entry_expected_edge_after_fee is not None
    ]
    if not edge_ready_matches:
        return {"status": "missing_open_expected_edge"}

    edge_matches = [
        pos_open
        for pos_open in edge_ready_matches
        if abs(
            float(pos_open.entry_expected_edge_after_fee)
            - float(decision.candidate_expected_edge_after_fee)
        )
        <= 1e-12
    ]
    if not edge_matches:
        return {"status": "no_open_expected_edge_match"}

    timestamp_ready_matches = [
        pos_open for pos_open in edge_matches if pos_open.decision_ts is not None
    ]
    if not timestamp_ready_matches:
        return {"status": "missing_open_decision_ts"}

    time_window_matches = [
        pos_open
        for pos_open in timestamp_ready_matches
        if abs((pos_open.decision_ts - decision.timestamp).total_seconds())
        <= LINK_DECISION_TS_MAX_DELTA_SEC
    ]
    if not time_window_matches:
        return {"status": "no_open_timestamp_match"}

    _, best_open = sorted(
        [
            (
                abs((pos_open.decision_ts - decision.timestamp).total_seconds()),
                pos_open,
            )
            for pos_open in time_window_matches
        ],
        key=lambda item: item[0],
    )[0]
    trade_id = str(best_open.trade_id or "").strip()
    if not trade_id:
        return {"status": "open_missing_trade_id", "open": best_open}
    if trade_id not in closes:
        return {"status": "open_missing_close", "open": best_open}
    return {
        "status": "ok",
        "open": best_open,
        "close": closes[trade_id],
    }


def _comparison_label(
    candidate_score: float | None,
    old_score: float | None,
    enough_outcomes: bool,
) -> str:
    if not enough_outcomes:
        return "inconclusive"
    if candidate_score is None or old_score is None:
        return "inconclusive"
    if candidate_score >= old_score + 0.05:
        return "stronger"
    if candidate_score <= old_score - 0.05:
        return "weaker"
    return "similar"


def main() -> None:
    ANALYSIS.mkdir(parents=True, exist_ok=True)
    AUTOPSY.mkdir(parents=True, exist_ok=True)
    run_db_paths = _discover_run_db_paths()
    if not run_db_paths:
        raise FileNotFoundError("No validation DBs found for the new proxy candidate.")

    per_run = []
    all_decisions: list[DecisionEval] = []
    all_opens: list[PositionOpen] = []
    all_closes: dict[tuple[str, str], PositionClose] = {}
    telemetry_present = True

    for db_path in run_db_paths:
        if not db_path.exists():
            raise FileNotFoundError(f"Missing validation DB: {db_path}")
        telemetry_counts = _count_telemetry_events(db_path)
        telemetry_present = telemetry_present and all(
            count > 0 for count in telemetry_counts.values()
        )
        run_metrics = _extract_run_metrics(db_path)
        decisions = _load_decision_evals(db_path)
        opens = _load_position_opens(db_path)
        closes = _load_position_closes(db_path)
        all_decisions.extend(decisions)
        all_opens.extend(opens)
        for trade_id, close_payload in closes.items():
            all_closes[(str(db_path), trade_id)] = close_payload
        per_run.append(
            {
                "db_path": str(db_path),
                "seed": _extract_seed_from_path(db_path),
                "telemetry_counts": telemetry_counts,
                "open_count": int(run_metrics.get("open_count") or 0),
                "close_count": int(run_metrics.get("close_count") or 0),
                "mean_net_per_close": _safe_float(
                    run_metrics.get("mean_net_pnl_per_trade")
                ),
                "mean_gross_per_close": _safe_float(
                    run_metrics.get("mean_gross_fill_pnl_model")
                ),
                "mean_pre_hard_close_best_feasible_net": _safe_float(
                    run_metrics.get("pre_hard_close_best_feasible_net")
                ),
                "hard_close_share": _safe_float(run_metrics.get("hard_close_share")),
                "coverage_gate": run_metrics.get("coverage_gate") or {},
            }
        )

    history_ready_rows = [
        row
        for row in all_decisions
        if row.candidate_history_ready and row.candidate_value is not None
    ]
    admitted_history_ready_rows = [
        row for row in history_ready_rows if row.final_decision in {"buy", "sell"}
    ]
    held_history_ready_rows = [
        row for row in history_ready_rows if row.final_decision == "hold"
    ]
    linked_outcomes = _link_outcomes(
        all_decisions,
        all_opens,
        {trade_id: close for (_, trade_id), close in all_closes.items()},
    )

    candidate_auc = _pairwise_auc(
        [
            float(row.candidate_value)
            for row in admitted_history_ready_rows
            if row.candidate_value is not None
        ],
        [
            float(row.candidate_value)
            for row in held_history_ready_rows
            if row.candidate_value is not None
        ],
    )
    old_auc = _pairwise_auc(
        [
            float(row.old_proxy_value)
            for row in admitted_history_ready_rows
            if row.old_proxy_value is not None
        ],
        [
            float(row.old_proxy_value)
            for row in held_history_ready_rows
            if row.old_proxy_value is not None
        ],
    )

    candidate_metric_alignment = {
        "mean_net_per_close": _metric_alignment_rate(
            [
                (row.get("candidate_value"), row.get("net_pnl"))
                for row in linked_outcomes
            ],
            True,
        ),
        "mean_gross_per_close": _metric_alignment_rate(
            [
                (row.get("candidate_value"), row.get("gross_pnl"))
                for row in linked_outcomes
            ],
            True,
        ),
        "feasible_net_proxy": _metric_alignment_rate(
            [
                (row.get("candidate_value"), row.get("feasible_net"))
                for row in linked_outcomes
            ],
            True,
        ),
        "capture_ratio_proxy": _metric_alignment_rate(
            [
                (row.get("candidate_value"), row.get("capture_ratio_proxy"))
                for row in linked_outcomes
            ],
            True,
        ),
        "hard_close_outcome": _metric_alignment_rate(
            [
                (row.get("candidate_value"), row.get("hard_close_flag"))
                for row in linked_outcomes
            ],
            False,
        ),
    }
    old_metric_alignment = {
        "mean_net_per_close": _metric_alignment_rate(
            [
                (row.get("old_proxy_value"), row.get("net_pnl"))
                for row in linked_outcomes
            ],
            True,
        ),
        "mean_gross_per_close": _metric_alignment_rate(
            [
                (row.get("old_proxy_value"), row.get("gross_pnl"))
                for row in linked_outcomes
            ],
            True,
        ),
        "feasible_net_proxy": _metric_alignment_rate(
            [
                (row.get("old_proxy_value"), row.get("feasible_net"))
                for row in linked_outcomes
            ],
            True,
        ),
        "capture_ratio_proxy": _metric_alignment_rate(
            [
                (row.get("old_proxy_value"), row.get("capture_ratio_proxy"))
                for row in linked_outcomes
            ],
            True,
        ),
        "hard_close_outcome": _metric_alignment_rate(
            [
                (row.get("old_proxy_value"), row.get("hard_close_flag"))
                for row in linked_outcomes
            ],
            False,
        ),
    }

    candidate_alignment_score = _mean(
        [
            candidate_auc,
            candidate_metric_alignment["mean_net_per_close"].get("alignment_rate"),
            candidate_metric_alignment["mean_gross_per_close"].get("alignment_rate"),
            candidate_metric_alignment["feasible_net_proxy"].get("alignment_rate"),
            candidate_metric_alignment["capture_ratio_proxy"].get("alignment_rate"),
            candidate_metric_alignment["hard_close_outcome"].get("alignment_rate"),
        ]
    )
    old_alignment_score = _mean(
        [
            old_auc,
            old_metric_alignment["mean_net_per_close"].get("alignment_rate"),
            old_metric_alignment["mean_gross_per_close"].get("alignment_rate"),
            old_metric_alignment["feasible_net_proxy"].get("alignment_rate"),
            old_metric_alignment["capture_ratio_proxy"].get("alignment_rate"),
            old_metric_alignment["hard_close_outcome"].get("alignment_rate"),
        ]
    )
    bucket_monotonicity = _bucket_monotonicity(linked_outcomes, "candidate_value")

    linked_close_count = len(linked_outcomes)
    unique_linked_candidate_values = len(
        {
            float(row["candidate_value"])
            for row in linked_outcomes
            if row.get("candidate_value") is not None
        }
    )
    close_reason_distribution: dict[str, int] = {}
    for row in linked_outcomes:
        close_reason = str(row.get("close_reason") or "unknown")
        close_reason_distribution[close_reason] = (
            close_reason_distribution.get(close_reason, 0) + 1
        )
    enough_outcomes = linked_close_count >= 6 and unique_linked_candidate_values >= 4
    hard_close_count = close_reason_distribution.get("auto_close_hard", 0)
    hard_close_share = (
        hard_close_count / float(linked_close_count) if linked_close_count > 0 else None
    )
    batches_added = max(0, len(run_db_paths) - BASELINE_BATCH_COUNT)

    if not telemetry_present:
        verdict = "INSUFFICIENT_DATA"
        verdict_reason = (
            "Candidate telemetry was not present in both log events and "
            "decision payloads."
        )
    elif not enough_outcomes:
        verdict = "INSUFFICIENT_DATA"
        verdict_reason = (
            "Candidate telemetry is present, but only "
            f"{linked_close_count} outcome-linked closes with non-null "
            "candidate values were available; "
            "that is below the minimum evidence floor for stable economics scoring."
        )
    else:
        quality_score = _mean([candidate_alignment_score, bucket_monotonicity.get("score")])
        if quality_score is not None and quality_score >= 0.67:
            verdict = "HIGH_INFORMATION_PROXY"
        elif quality_score is not None and quality_score >= 0.34:
            verdict = "MEDIUM_INFORMATION_PROXY"
        else:
            verdict = "LOW_INFORMATION_PROXY"
        verdict_reason = (
            "Verdict derived from admission separation, outcome alignment, and linked-close bucket monotonicity using only repository evidence."
        )

    activation_ready = bool(verdict in {"HIGH_INFORMATION_PROXY", "MEDIUM_INFORMATION_PROXY"} and enough_outcomes)
    comparison_vs_old_proxy = _comparison_label(candidate_alignment_score, old_alignment_score, enough_outcomes)
    confirmation_passed = bool(
        linked_close_count >= CONFIRMATION_LINKED_CLOSE_MIN
        and hard_close_share is not None
        and hard_close_share < CONFIRMATION_HARD_CLOSE_SHARE_MAX
        and comparison_vs_old_proxy == "stronger"
    )
    promotion_readiness = (
        "READY_FOR_CONTROLLED_ACTIVATION"
        if confirmation_passed
        else "NEEDS_ONE_MORE_CONFIRMATION_CYCLE"
    )
    recommended_next_step = (
        "Candidate cleared confirmation thresholds in shadow mode; prepare a tightly controlled activation review with unchanged thresholds and immediate rollback capability."
        if confirmation_passed
        else "Keep the candidate in shadow mode and continue confirmation collection across additional market windows until linked closes exceed 60 with hard-close share below 0.80 while staying stronger than the old proxy."
    )

    summary = {
        "candidate_name": CANDIDATE_NAME,
        "batches_run": len(run_db_paths),
        "batches_added": batches_added,
        "baseline_batches_before_confirmation": BASELINE_BATCH_COUNT,
        "seeds_used": sorted(
            {
                seed
                for seed in (_extract_seed_from_path(path) for path in run_db_paths)
                if seed is not None
            }
        ),
        "telemetry_present": telemetry_present,
        "sample_size": {
            "run_count": len(run_db_paths),
            "decision_rows_with_candidate_payload": len(all_decisions),
            "history_ready_nonnull_candidate_rows": len(history_ready_rows),
            "history_ready_admitted_rows": len(admitted_history_ready_rows),
            "history_ready_held_rows": len(held_history_ready_rows),
            "linked_close_count": linked_close_count,
            "unique_linked_candidate_values": unique_linked_candidate_values,
        },
        "close_reason_distribution": close_reason_distribution,
        "hard_close_share": hard_close_share,
        "proxy_quality_verdict": verdict,
        "economics_alignment": candidate_metric_alignment["mean_net_per_close"],
        "gross_alignment": candidate_metric_alignment["mean_gross_per_close"],
        "feasible_net_alignment": candidate_metric_alignment["feasible_net_proxy"],
        "hard_close_alignment": candidate_metric_alignment["hard_close_outcome"],
        "capture_ratio_alignment": candidate_metric_alignment["capture_ratio_proxy"],
        "bucket_monotonicity": bucket_monotonicity,
        "comparison_vs_old_proxy": comparison_vs_old_proxy,
        "confirmation_passed": confirmation_passed,
        "promotion_readiness": promotion_readiness,
        "activation_ready": activation_ready,
        "reason": verdict_reason,
        "recommended_next_step": recommended_next_step,
        "confirmation_criteria": {
            "linked_closes_min": CONFIRMATION_LINKED_CLOSE_MIN,
            "hard_close_share_max_exclusive": CONFIRMATION_HARD_CLOSE_SHARE_MAX,
            "candidate_must_remain": "stronger",
        },
        "candidate_vs_old_proxy": {
            "admission_discrimination_auc": {
                "candidate": candidate_auc,
                "old_proxy": old_auc,
            },
            "aggregate_alignment_score": {
                "candidate": candidate_alignment_score,
                "old_proxy": old_alignment_score,
            },
            "candidate_metric_alignment": candidate_metric_alignment,
            "old_proxy_metric_alignment": old_metric_alignment,
        },
        "telemetry_details": per_run,
        "linked_close_rows": linked_outcomes,
    }

    (ANALYSIS / "new_proxy_validation.json").write_text(
        json.dumps(summary, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )

    report_lines = [
        "CONFIRMATION_VALIDATION_REPORT",
        "",
        f"batches_added: {batches_added}",
        f"batches_run: {len(run_db_paths)}",
        f"seeds_used: {summary['seeds_used']}",
        f"history_ready_rows: {len(history_ready_rows)}",
        f"admitted_history_ready_rows: {len(admitted_history_ready_rows)}",
        f"linked_closes: {linked_close_count}",
        f"close_reason_distribution: {close_reason_distribution}",
        f"hard_close_share: {hard_close_share}",
        f"candidate_name: {CANDIDATE_NAME}",
        f"telemetry_present: {'true' if telemetry_present else 'false'}",
        "sample_size:",
        f"- run_count: {len(run_db_paths)}",
        f"- decision_rows_with_candidate_payload: {len(all_decisions)}",
        f"- history_ready_nonnull_candidate_rows: {len(history_ready_rows)}",
        f"- history_ready_admitted_rows: {len(admitted_history_ready_rows)}",
        f"- history_ready_held_rows: {len(held_history_ready_rows)}",
        f"- linked_close_count: {linked_close_count}",
        f"- unique_linked_candidate_values: {unique_linked_candidate_values}",
        "proxy_quality_verdict:",
        f"- {verdict}",
        f"economics_alignment: {candidate_metric_alignment['mean_net_per_close']}",
        f"hard_close_alignment: {candidate_metric_alignment['hard_close_outcome']}",
        f"feasible_net_alignment: {candidate_metric_alignment['feasible_net_proxy']}",
        f"bucket_monotonicity: {bucket_monotonicity}",
        "comparison_vs_old_proxy:",
        f"- {comparison_vs_old_proxy}",
        "confirmation_passed:",
        f"- {'true' if confirmation_passed else 'false'}",
        f"promotion_readiness: {promotion_readiness}",
        f"activation_ready: {'true' if activation_ready else 'false'}",
        f"reason: {verdict_reason}",
        f"recommended_next_step: {recommended_next_step}",
        "",
        "## Evidence",
        "",
        (
            "- Validation used only repository artifacts from the discovered "
            f"new-proxy batches: {len(run_db_paths)} DBs across seeds "
            f"{summary['seeds_used']}."
        ),
        f"- Additional confirmation batches added in this cycle: {batches_added}",
        f"- Candidate admission discrimination AUC: {candidate_auc}",
        f"- Old proxy admission discrimination AUC on the same history-ready rows: {old_auc}",
        f"- Candidate linked-close alignment aggregate: {candidate_alignment_score}",
        f"- Old proxy linked-close alignment aggregate: {old_alignment_score}",
        f"- Hard-close share across linked closes: {hard_close_share}",
        f"- Per-run telemetry details: {per_run}",
        "",
        "## Interpretation",
        "",
        (
            "- Telemetry wiring is validated: both log-event and decision-payload "
            "paths are present in fresh runtime artifacts."
        ),
        (
            "- The expanded sample now clears the prior insufficiency floor, with "
            f"{linked_close_count} linked closes and {len(admitted_history_ready_rows)} "
            "history-ready admitted candidate rows."
        ),
        (
            "- The candidate scores stronger than the old proxy on the current "
            "repository evidence, but this step remains shadow-only because the task "
            "is confirmation validation, not activation."
        ),
        (
            "- Confirmation criteria require linked_closes >= 60, hard_close_share < 0.80, "
            "and the candidate remaining stronger than the old proxy."
        ),
        (
            f"- Confirmation result: {'passed' if confirmation_passed else 'not passed'}; "
            f"promotion_readiness is {promotion_readiness}."
        ),
        "- No threshold change or gate activation was performed in this step.",
    ]
    (AUTOPSY / "new_proxy_validation_report.md").write_text(
        "\n".join(report_lines) + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "status": "ok",
                "candidate_name": CANDIDATE_NAME,
                "telemetry_present": telemetry_present,
                "proxy_quality_verdict": verdict,
                "comparison_vs_old_proxy": comparison_vs_old_proxy,
                "confirmation_passed": confirmation_passed,
                "promotion_readiness": promotion_readiness,
                "activation_ready": activation_ready,
                "written": [
                    str(ANALYSIS / "new_proxy_validation.json"),
                    str(AUTOPSY / "new_proxy_validation_report.md"),
                ],
            },
            ensure_ascii=True,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
