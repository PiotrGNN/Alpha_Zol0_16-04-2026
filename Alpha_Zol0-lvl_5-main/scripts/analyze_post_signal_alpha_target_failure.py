from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any


WORKDIR = Path(__file__).resolve().parents[1]
EVENT_NAME = "post_signal_trajectory_v2"
RUNTIME_SOURCE = "rolling_quote_window"
STRONGER_FAMILIES = {"MICROBREAKOUT", "MOMENTUM", "MEANREVERSION"}
BASELINE_FAMILIES = {"TRENDFOLLOWING"}
CONTAMINATION_KEYS = ("seed", "fallback", "mock", "force_open", "forced_cycle")

CLASS_SIGNALS_WEAK = "POST_SIGNAL_NO_TARGETS_BECAUSE_SIGNALS_WEAK"
CLASS_TARGET_TOO_STRICT = "POST_SIGNAL_NO_TARGETS_BECAUSE_TARGET_TOO_STRICT"
CLASS_COST_DOMINATES = "POST_SIGNAL_NO_TARGETS_BECAUSE_COST_BURDEN_DOMINATES"
CLASS_HORIZON_MISMATCH = "POST_SIGNAL_NO_TARGETS_BECAUSE_HORIZON_MISMATCH"
CLASS_ANALYZER_FILTER = "POST_SIGNAL_NO_TARGETS_BECAUSE_ANALYZER_FILTER_TOO_STRICT"
CLASS_MISSING_FIELDS = "POST_SIGNAL_NO_TARGETS_BECAUSE_MISSING_FIELDS"
CLASS_SAMPLE_TOO_SMALL = "POST_SIGNAL_NO_TARGETS_BECAUSE_SAMPLE_TOO_SMALL"
CLASS_INCONCLUSIVE = "POST_SIGNAL_ALPHA_TARGET_AUTOPSY_INCONCLUSIVE"

REQUIRED_FIELDS = (
    "symbol",
    "canonical_strategy",
    "side",
    "source",
    "horizon_ticks",
    "signed_gross_move",
    "estimated_cost",
    "signed_net_move",
    "expected_net_after_cost",
)


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def canonical_strategy(strategy: Any) -> str:
    normalized = str(strategy or "").strip().lower().replace("-", "_").replace(" ", "")
    aliases = {
        "microbreakoutv2": "MICROBREAKOUT",
        "microbreakout": "MICROBREAKOUT",
        "micro_breakout": "MICROBREAKOUT",
        "momentumv2": "MOMENTUM",
        "momentum": "MOMENTUM",
        "meanreversionv2": "MEANREVERSION",
        "meanreversion": "MEANREVERSION",
        "mean_reversion": "MEANREVERSION",
        "trendfollowingv2": "TRENDFOLLOWING",
        "trendfollowing": "TRENDFOLLOWING",
        "trend_following": "TRENDFOLLOWING",
    }
    return aliases.get(normalized, str(strategy or "").strip().upper())


def _is_contaminated(payload: dict[str, Any]) -> bool:
    flags = payload.get("contamination_flags")
    if not isinstance(flags, dict):
        return False
    for key in CONTAMINATION_KEYS:
        value = flags.get(key, 0)
        if value is True:
            return True
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value != 0:
            return True
        if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False


def _load_payloads_from_db(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    try:
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "logs" not in tables:
            return []
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(logs)").fetchall()
        }
        event_col = "event" if "event" in columns else "event_type" if "event_type" in columns else None
        details_col = "details" if "details" in columns else "payload" if "payload" in columns else None
        timestamp_col = "timestamp" if "timestamp" in columns else "ts" if "ts" in columns else None
        if event_col is None or details_col is None:
            return []
        selected = [event_col, details_col]
        if timestamp_col:
            selected.append(timestamp_col)
        payloads: list[dict[str, Any]] = []
        for row in conn.execute(f"SELECT {', '.join(selected)} FROM logs ORDER BY rowid ASC"):
            values = dict(zip(selected, row))
            if str(values.get(event_col)) != EVENT_NAME:
                continue
            try:
                payload = json.loads(str(values.get(details_col) or "{}"))
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            if timestamp_col:
                payload.setdefault("db_timestamp", values.get(timestamp_col))
            payload["db_path"] = str(db_path)
            payloads.append(payload)
        return payloads
    finally:
        conn.close()


def _normalize(payload: dict[str, Any]) -> dict[str, Any]:
    strategy = canonical_strategy(payload.get("canonical_strategy") or payload.get("strategy"))
    gross = _safe_float(payload.get("signed_gross_move"))
    cost = _safe_float(payload.get("estimated_cost"))
    net = _safe_float(payload.get("signed_net_move"))
    mfe = max(gross, 0.0) if gross is not None else None
    mae = abs(min(gross, 0.0)) if gross is not None else None
    stop_risk = _safe_float(payload.get("stop_risk") or payload.get("stop_risk_usdt") or payload.get("stop_loss_net_usdt"))
    mfe_stop_ratio = (mfe / stop_risk) if mfe is not None and stop_risk not in (None, 0.0) else None
    return {
        "db_path": payload.get("db_path"),
        "db_timestamp": payload.get("db_timestamp"),
        "symbol": str(payload.get("symbol") or "").upper(),
        "strategy": payload.get("strategy"),
        "canonical_strategy": strategy,
        "side": str(payload.get("side") or "").lower(),
        "source": payload.get("source"),
        "runtime_profile_key": payload.get("runtime_profile_key"),
        "horizon_ticks": _safe_int(payload.get("horizon_ticks"), 0),
        "signed_gross_move": gross,
        "estimated_cost": cost,
        "signed_net_move": net,
        "mfe": mfe,
        "mae": mae,
        "mfe_minus_cost": (mfe - cost) if mfe is not None and cost is not None else None,
        "expected_move": _safe_float(payload.get("expected_move")),
        "expected_net_after_cost": _safe_float(payload.get("expected_net_after_cost")),
        "expected_edge_after_fee": _safe_float(payload.get("expected_edge_after_fee")),
        "expected_gross_before_cost": _safe_float(payload.get("expected_gross_before_cost")),
        "stop_risk": stop_risk,
        "mfe_stop_risk_ratio": mfe_stop_ratio,
        "reason_code": payload.get("reason_code"),
        "contaminated": _is_contaminated(payload),
        "contamination_flags": payload.get("contamination_flags") if isinstance(payload.get("contamination_flags"), dict) else {},
        "missing_fields": [field for field in REQUIRED_FIELDS if payload.get(field) in (None, "")],
    }


def _counter(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get(key) or "") for row in rows).items()))


def _median(values: list[float]) -> float | None:
    return float(median(values)) if values else None


def _horizon_distribution(rows: list[dict[str, Any]]) -> dict[str, dict[str, float | int | None]]:
    buckets: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[int(row.get("horizon_ticks") or 0)].append(row)
    distribution: dict[str, dict[str, float | int | None]] = {}
    for horizon, bucket in sorted(buckets.items()):
        mfes = [float(row["mfe"]) for row in bucket if row.get("mfe") is not None]
        maes = [float(row["mae"]) for row in bucket if row.get("mae") is not None]
        costs = [float(row["estimated_cost"]) for row in bucket if row.get("estimated_cost") is not None]
        mfe_minus_cost = [float(row["mfe_minus_cost"]) for row in bucket if row.get("mfe_minus_cost") is not None]
        distribution[str(horizon)] = {
            "event_count": len(bucket),
            "max_mfe": max(mfes) if mfes else None,
            "median_mfe": _median(mfes),
            "max_mae": max(maes) if maes else None,
            "median_mae": _median(maes),
            "median_estimated_cost": _median(costs),
            "max_mfe_minus_cost_burden": max(mfe_minus_cost) if mfe_minus_cost else None,
            "median_mfe_minus_cost_burden": _median(mfe_minus_cost),
        }
    return distribution


def _best_by_group(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get(key) or "")].append(row)
    ranked = []
    for value, bucket in buckets.items():
        nets = [float(row["signed_net_move"]) for row in bucket if row.get("signed_net_move") is not None]
        mfes = [float(row["mfe"]) for row in bucket if row.get("mfe") is not None]
        ranked.append(
            {
                key: value,
                "event_count": len(bucket),
                "best_signed_net_move": max(nets) if nets else None,
                "best_mfe": max(mfes) if mfes else None,
            }
        )
    ranked.sort(key=lambda row: row.get("best_signed_net_move") if row.get("best_signed_net_move") is not None else -999.0, reverse=True)
    return ranked


def _missing_field_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for row in rows:
        for field in row.get("missing_fields") or []:
            counts[field] += 1
    return {field: int(counts.get(field, 0)) for field in REQUIRED_FIELDS}


def _near_target_counts(rows: list[dict[str, Any]], target: float) -> dict[str, int]:
    thresholds = {
        "25pct": target * 0.25,
        "50pct": target * 0.50,
        "75pct": target * 0.75,
        "90pct": target * 0.90,
    }
    values = [float(row["signed_net_move"]) for row in rows if row.get("signed_net_move") is not None]
    return {name: sum(1 for value in values if value >= threshold) for name, threshold in thresholds.items()}


def _family_comparison(rows: list[dict[str, Any]]) -> dict[str, Any]:
    non_trend = [row for row in rows if row.get("canonical_strategy") in STRONGER_FAMILIES]
    trend = [row for row in rows if row.get("canonical_strategy") in BASELINE_FAMILIES]
    non_trend_values = [float(row["signed_net_move"]) for row in non_trend if row.get("signed_net_move") is not None]
    trend_values = [float(row["signed_net_move"]) for row in trend if row.get("signed_net_move") is not None]
    return {
        "non_trendfollowing_event_count": len(non_trend),
        "trendfollowing_event_count": len(trend),
        "best_non_trendfollowing_net": max(non_trend_values) if non_trend_values else None,
        "best_trendfollowing_net": max(trend_values) if trend_values else None,
        "non_trendfollowing_beats_baseline": bool(
            non_trend_values and (not trend_values or max(non_trend_values) > max(trend_values))
        ),
    }


def _expected_vs_realized(rows: list[dict[str, Any]]) -> dict[str, Any]:
    paired = [
        row for row in rows if row.get("expected_net_after_cost") is not None and row.get("mfe") is not None
    ]
    expected = [float(row["expected_net_after_cost"]) for row in paired]
    realized = [float(row["mfe"]) for row in paired]
    return {
        "paired_count": len(paired),
        "max_expected_net_after_cost": max(expected) if expected else None,
        "median_expected_net_after_cost": _median(expected),
        "max_realized_mfe": max(realized) if realized else None,
        "median_realized_mfe": _median(realized),
    }


def _classify(
    clean_rows: list[dict[str, Any]],
    contaminated_rows: list[dict[str, Any]],
    missing_counts: dict[str, int],
    near_counts: dict[str, int],
    target: float,
    min_samples: int,
) -> str:
    if not clean_rows and contaminated_rows:
        return CLASS_INCONCLUSIVE
    if not clean_rows:
        return CLASS_SAMPLE_TOO_SMALL
    critical_missing = sum(missing_counts.get(field, 0) for field in ("signed_gross_move", "estimated_cost", "signed_net_move"))
    if critical_missing:
        return CLASS_MISSING_FIELDS
    net_values = [float(row["signed_net_move"]) for row in clean_rows if row.get("signed_net_move") is not None]
    mfe_values = [float(row["mfe"]) for row in clean_rows if row.get("mfe") is not None]
    cost_values = [float(row["estimated_cost"]) for row in clean_rows if row.get("estimated_cost") is not None]
    max_net = max(net_values) if net_values else None
    max_mfe = max(mfe_values) if mfe_values else None
    median_cost = _median(cost_values)
    if near_counts.get("90pct", 0) and max_net is not None and max_net < target:
        return CLASS_TARGET_TOO_STRICT
    if max_mfe is not None and median_cost is not None and max_mfe <= median_cost:
        return CLASS_COST_DOMINATES
    if len(clean_rows) < int(min_samples):
        return CLASS_SAMPLE_TOO_SMALL
    by_horizon = _best_by_group(clean_rows, "horizon_ticks")
    if len(by_horizon) > 1 and near_counts.get("25pct", 0) and by_horizon[0].get("best_signed_net_move") is not None:
        return CLASS_HORIZON_MISMATCH
    if near_counts.get("25pct", 0):
        return CLASS_ANALYZER_FILTER
    return CLASS_SIGNALS_WEAK


def analyze_post_signal_alpha_target_failure(runtime_artifact_path: Path | str) -> dict[str, Any]:
    artifact_path = Path(runtime_artifact_path)
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    inputs = artifact.get("inputs") if isinstance(artifact.get("inputs"), dict) else {}
    db_paths = [Path(path) for path in inputs.get("db_paths", [])]
    target = float(inputs.get("min_p95_signed_net", 0.12))
    min_samples = int(inputs.get("min_samples", 20))
    raw_payloads = [payload for db_path in db_paths for payload in _load_payloads_from_db(db_path)]
    rows = [_normalize(payload) for payload in raw_payloads]
    clean_rows = [
        row for row in rows if not row["contaminated"] and row.get("source") == RUNTIME_SOURCE
    ]
    contaminated_rows = [row for row in rows if row["contaminated"]]
    missing_counts = _missing_field_counts(clean_rows)
    near_counts = _near_target_counts(clean_rows, target)
    best_events = sorted(
        clean_rows,
        key=lambda row: row.get("signed_net_move") if row.get("signed_net_move") is not None else -999.0,
        reverse=True,
    )[:20]
    worst_events = sorted(
        clean_rows,
        key=lambda row: row.get("signed_gross_move") if row.get("signed_gross_move") is not None else 999.0,
    )[:20]
    classification = _classify(clean_rows, contaminated_rows, missing_counts, near_counts, target, min_samples)
    report = {
        "classification": classification,
        "inputs": {
            "runtime_artifact_path": str(artifact_path),
            "db_paths": [str(path) for path in db_paths],
            "min_samples": min_samples,
            "min_p95_signed_net": target,
            "runtime_source_required": RUNTIME_SOURCE,
        },
        "summary": {
            "runtime_artifact_classification": artifact.get("classification"),
            "trajectory_event_count": len(rows),
            "clean_event_count": len(clean_rows),
            "contaminated_event_count": len(contaminated_rows),
            "alpha_target_count": int((artifact.get("summary") or {}).get("alpha_target_count", 0)),
            "db_count": len(db_paths),
        },
        "event_count_by_strategy": _counter(clean_rows, "canonical_strategy"),
        "event_count_by_symbol": _counter(clean_rows, "symbol"),
        "event_count_by_side": _counter(clean_rows, "side"),
        "near_target_counts": near_counts,
        "horizon_distributions": _horizon_distribution(clean_rows),
        "strategy_ranking": _best_by_group(clean_rows, "canonical_strategy"),
        "symbol_ranking": _best_by_group(clean_rows, "symbol"),
        "side_ranking": _best_by_group(clean_rows, "side"),
        "strategy_family_comparison": _family_comparison(clean_rows),
        "expected_net_vs_realized_post_signal_mfe": _expected_vs_realized(clean_rows),
        "best_20_trajectory_events_by_net_opportunity": best_events,
        "best_events_by_net_opportunity": best_events,
        "worst_20_trajectory_events_by_adverse_movement": worst_events,
        "worst_events_by_adverse_movement": worst_events,
        "missing_field_counts": missing_counts,
        "decision_answers": _decision_answers(classification, clean_rows, near_counts, target, min_samples),
    }
    return report


def _decision_answers(
    classification: str,
    clean_rows: list[dict[str, Any]],
    near_counts: dict[str, int],
    target: float,
    min_samples: int,
) -> dict[str, Any]:
    best = max(
        (row for row in clean_rows if row.get("signed_net_move") is not None),
        key=lambda row: float(row["signed_net_move"]),
        default=None,
    )
    family_comparison = _family_comparison(clean_rows)
    return {
        "why_alpha_target_count_zero": classification,
        "any_clean_event_close_to_alpha_target": bool(near_counts.get("75pct", 0) or near_counts.get("90pct", 0)),
        "best_near_target_event": best,
        "target_threshold": target,
        "min_samples_required": min_samples,
        "best_strategy_family": best.get("canonical_strategy") if best else None,
        "best_symbol_side": f"{best.get('symbol')}:{best.get('side')}" if best else None,
        "non_trendfollowing_better_than_trendfollowing_baseline": family_comparison["non_trendfollowing_beats_baseline"],
        "focused_paper_observation_candidate": (
            f"{best.get('symbol')}:{best.get('canonical_strategy')}:{best.get('side')}"
            if best and best.get("canonical_strategy") in STRONGER_FAMILIES
            else None
        ),
        "telemetry_only_extension_needed": classification in {CLASS_HORIZON_MISMATCH, CLASS_MISSING_FIELDS},
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    answers = report["decision_answers"]
    lines = [
        "# Post-Signal Alpha Target Failure Autopsy",
        "",
        f"- classification: `{report['classification']}`",
        f"- trajectory_event_count: `{summary['trajectory_event_count']}`",
        f"- clean_event_count: `{summary['clean_event_count']}`",
        f"- contaminated_event_count: `{summary['contaminated_event_count']}`",
        f"- alpha_target_count: `{summary['alpha_target_count']}`",
        f"- target_threshold: `{report['inputs']['min_p95_signed_net']}`",
        f"- min_samples: `{report['inputs']['min_samples']}`",
        "",
        "## Root Cause Answers",
        f"- why_alpha_target_count_zero: `{answers['why_alpha_target_count_zero']}`",
        f"- any_clean_event_close_to_alpha_target: `{answers['any_clean_event_close_to_alpha_target']}`",
        f"- best_strategy_family: `{answers['best_strategy_family']}`",
        f"- best_symbol_side: `{answers['best_symbol_side']}`",
        f"- non_trendfollowing_better_than_trendfollowing_baseline: `{answers['non_trendfollowing_better_than_trendfollowing_baseline']}`",
        f"- focused_paper_observation_candidate: `{answers['focused_paper_observation_candidate']}`",
        f"- telemetry_only_extension_needed: `{answers['telemetry_only_extension_needed']}`",
        "",
        "## Near Target Counts",
    ]
    for key, value in report["near_target_counts"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Strategy Ranking"])
    for row in report["strategy_ranking"][:10]:
        lines.append(
            "- `{strategy}` events=`{events}` best_net=`{net}` best_mfe=`{mfe}`".format(
                strategy=row["canonical_strategy"],
                events=row["event_count"],
                net=row["best_signed_net_move"],
                mfe=row["best_mfe"],
            )
        )
    lines.extend(["", "## Best Events"])
    for row in report["best_20_trajectory_events_by_net_opportunity"][:10]:
        lines.append(
            "- `{strategy}:{symbol}:{side}:h{horizon}` net=`{net}` gross=`{gross}` cost=`{cost}`".format(
                strategy=row["canonical_strategy"],
                symbol=row["symbol"],
                side=row["side"],
                horizon=row["horizon_ticks"],
                net=row["signed_net_move"],
                gross=row["signed_gross_move"],
                cost=row["estimated_cost"],
            )
        )
    lines.extend(["", "## Missing Fields"])
    for field, value in report["missing_field_counts"].items():
        lines.append(f"- {field}: `{value}`")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runtime-artifact",
        default="analysis/runtime_post_signal_trajectory_current.json",
    )
    parser.add_argument(
        "--output-json",
        default="analysis/post_signal_alpha_target_failure_current.json",
    )
    parser.add_argument(
        "--output-md",
        default="analysis/post_signal_alpha_target_failure_current.md",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = analyze_post_signal_alpha_target_failure(WORKDIR / args.runtime_artifact)
    output_json = WORKDIR / args.output_json
    output_md = WORKDIR / args.output_md
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    output_md.write_text(render_markdown(report), encoding="utf-8")
    print(report["classification"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
