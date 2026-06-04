from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any


WORKDIR = Path(__file__).resolve().parents[1]
EVENT_NAME = "post_signal_trajectory_v2"
RUNTIME_SOURCE = "rolling_quote_window"

CLASS_CANDIDATE_FOUND = "PROFITABILITY_OPERATING_POINT_CANDIDATE_FOUND"
CLASS_NO_OPERATING_POINT = "PROFITABILITY_OPERATING_POINT_NOT_FOUND_SIGNALS_TOO_WEAK"
CLASS_COST_DOMINATED = "PROFITABILITY_OPERATING_POINT_NOT_FOUND_COST_DOMINATED"
CLASS_CONTAMINATED = "PROFITABILITY_OPERATING_POINT_EVIDENCE_CONTAMINATED"
CLASS_TELEMETRY_GAP = "PROFITABILITY_OPERATING_POINT_BLOCKED_BY_TELEMETRY_GAP"

CONTAMINATION_KEYS = ("seed", "fallback", "mock", "force_open", "forced_cycle")
STRONGER_FAMILIES = {"MICROBREAKOUT", "MOMENTUM", "MEANREVERSION"}


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _canonical_strategy(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "")
    aliases = {
        "microbreakoutv2": "MICROBREAKOUT",
        "microbreakout": "MICROBREAKOUT",
        "momentumv2": "MOMENTUM",
        "momentum": "MOMENTUM",
        "meanreversionv2": "MEANREVERSION",
        "meanreversion": "MEANREVERSION",
        "mean_reversion": "MEANREVERSION",
        "trendfollowingv2": "TRENDFOLLOWING",
        "trendfollowing": "TRENDFOLLOWING",
    }
    return aliases.get(normalized, str(value or "").strip().upper())


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


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_payloads(db_path: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    try:
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "logs" not in tables:
            return []
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(logs)")}
        event_col = "event" if "event" in columns else "event_type" if "event_type" in columns else None
        details_col = "details" if "details" in columns else "payload" if "payload" in columns else None
        timestamp_col = "timestamp" if "timestamp" in columns else "ts" if "ts" in columns else None
        if event_col is None or details_col is None:
            return []
        selected = [event_col, details_col]
        if timestamp_col:
            selected.append(timestamp_col)
        rows = []
        for row in conn.execute(f"SELECT {', '.join(selected)} FROM logs ORDER BY rowid ASC"):
            values = dict(zip(selected, row))
            if values.get(event_col) != EVENT_NAME:
                continue
            try:
                payload = json.loads(str(values.get(details_col) or "{}"))
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            payload["db_path"] = str(db_path)
            if timestamp_col:
                payload["db_timestamp"] = values.get(timestamp_col)
            rows.append(payload)
        return rows
    finally:
        conn.close()


def _normalize(payload: dict[str, Any]) -> dict[str, Any]:
    strategy = _canonical_strategy(payload.get("canonical_strategy") or payload.get("strategy"))
    symbol = str(payload.get("symbol") or "").upper()
    side = str(payload.get("side") or "").lower()
    horizon = _safe_int(payload.get("horizon_ticks"))
    signed_net = _safe_float(payload.get("signed_net_move"))
    signed_gross = _safe_float(payload.get("signed_gross_move"))
    cost = _safe_float(payload.get("estimated_cost"))
    return {
        "candidate_key": f"{symbol}:{strategy}:{side}:h{horizon}",
        "symbol": symbol,
        "canonical_strategy": strategy,
        "side": side,
        "horizon_ticks": horizon,
        "source": payload.get("source"),
        "signed_net_move": signed_net,
        "signed_gross_move": signed_gross,
        "estimated_cost": cost,
        "contaminated": _is_contaminated(payload),
        "db_path": payload.get("db_path"),
        "db_timestamp": payload.get("db_timestamp"),
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    idx = (len(ordered) - 1) * percentile
    lower = int(idx)
    upper = min(lower + 1, len(ordered) - 1)
    weight = idx - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _bucket_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["canonical_strategy"] not in STRONGER_FAMILIES:
            continue
        if row.get("source") != RUNTIME_SOURCE:
            continue
        if row.get("signed_net_move") is None or row.get("estimated_cost") is None or row.get("signed_gross_move") is None:
            continue
        buckets[row["candidate_key"]].append(row)
    summaries = []
    for key, bucket in buckets.items():
        nets = [float(row["signed_net_move"]) for row in bucket]
        gross = [float(row["signed_gross_move"]) for row in bucket]
        costs = [float(row["estimated_cost"]) for row in bucket]
        wins = [value for value in nets if value > 0]
        losses = [abs(value) for value in nets if value <= 0]
        avg_win = mean(wins) if wins else 0.0
        avg_loss = mean(losses) if losses else 0.0
        win_rate = len(wins) / len(nets) if nets else 0.0
        payoff_ratio = (avg_win / avg_loss) if avg_loss > 0 else (999.0 if avg_win > 0 else 0.0)
        expectancy = mean(nets) if nets else 0.0
        median_cost = median(costs) if costs else 0.0
        median_positive_gross = median([value for value in gross if value > 0]) if any(value > 0 for value in gross) else 0.0
        cost_to_gross = (median_cost / median_positive_gross) if median_positive_gross > 0 else 999.0
        summaries.append(
            {
                "candidate_key": key,
                "symbol": bucket[0]["symbol"],
                "canonical_strategy": bucket[0]["canonical_strategy"],
                "side": bucket[0]["side"],
                "horizon_ticks": bucket[0]["horizon_ticks"],
                "sample_count": len(nets),
                "win_count": len(wins),
                "loss_count": len(losses),
                "win_rate": round(win_rate, 6),
                "avg_win_net": avg_win,
                "avg_loss_abs": avg_loss,
                "payoff_ratio": payoff_ratio,
                "expectancy_per_signal": expectancy,
                "median_cost": median_cost,
                "median_positive_gross": median_positive_gross,
                "cost_to_gross_ratio": cost_to_gross,
                "p05_signed_net": _percentile(nets, 0.05),
                "p50_signed_net": _percentile(nets, 0.50),
                "p95_signed_net": _percentile(nets, 0.95),
                "operating_point_score": expectancy * len(nets),
                "passes_operating_point": (
                    len(nets) >= 20
                    and win_rate >= 0.55
                    and payoff_ratio >= 1.0
                    and expectancy > 0.0
                    and cost_to_gross <= 0.35
                ),
            }
        )
    summaries.sort(
        key=lambda row: (
            bool(row["passes_operating_point"]),
            row["operating_point_score"],
            row["p95_signed_net"] or -999.0,
            row["sample_count"],
        ),
        reverse=True,
    )
    return summaries


def audit_operating_point(runtime_artifact: Path | str, blocker_artifact: Path | str) -> dict[str, Any]:
    runtime_path = Path(runtime_artifact)
    blocker_path = Path(blocker_artifact)
    runtime = _read_json(runtime_path)
    blocker = _read_json(blocker_path)
    db_paths = [Path(path) for path in ((runtime.get("inputs") or {}).get("db_paths") or [])]
    payloads = [payload for db_path in db_paths for payload in _load_payloads(db_path)]
    rows = [_normalize(payload) for payload in payloads]
    contaminated = [row for row in rows if row["contaminated"]]
    clean = [row for row in rows if not row["contaminated"]]
    missing_core_fields = sum(
        1
        for row in clean
        if row.get("signed_net_move") is None or row.get("signed_gross_move") is None or row.get("estimated_cost") is None
    )
    buckets = _bucket_summary(clean)
    passing = [row for row in buckets if row["passes_operating_point"]]
    cost_dominated = bool(buckets) and all(
        row["median_positive_gross"] <= row["median_cost"]
        for row in buckets
        if row["sample_count"] >= 20
    )
    if contaminated:
        classification = CLASS_CONTAMINATED
    elif missing_core_fields:
        classification = CLASS_TELEMETRY_GAP
    elif passing:
        classification = CLASS_CANDIDATE_FOUND
    elif cost_dominated:
        classification = CLASS_COST_DOMINATED
    else:
        classification = CLASS_NO_OPERATING_POINT
    return {
        "classification": classification,
        "inputs": {
            "runtime_artifact": str(runtime_path),
            "blocker_artifact": str(blocker_path),
            "db_paths": [str(path) for path in db_paths],
        },
        "summary": {
            "trajectory_event_count": len(rows),
            "clean_event_count": len(clean),
            "contaminated_event_count": len(contaminated),
            "bucket_count": len(buckets),
            "passing_bucket_count": len(passing),
            "position_open_count": (blocker.get("summary") or {}).get("position_open_count"),
            "blocker_classification": blocker.get("classification"),
        },
        "objective": {
            "sample_count_min": 20,
            "win_rate_min": 0.55,
            "payoff_ratio_min": 1.0,
            "expectancy_per_signal_min": 0.0,
            "cost_to_gross_ratio_max": 0.35,
            "profitability_claim": False,
        },
        "best_operating_point": passing[0] if passing else None,
        "ranked_buckets": buckets[:30],
        "decision": _decision(classification),
        "profitability_claim": False,
    }


def _decision(classification: str) -> dict[str, Any]:
    if classification == CLASS_CANDIDATE_FOUND:
        return {
            "next_step": "paper_validate_selected_operating_point_without_threshold_patch",
            "patch_runtime": False,
            "patch_strategy": False,
            "reason": "post-signal bucket has positive expectancy, sufficient sample, acceptable payoff, and acceptable cost burden",
        }
    if classification == CLASS_COST_DOMINATED:
        return {
            "next_step": "cost_model_or_spread_burden_audit",
            "patch_runtime": False,
            "patch_strategy": False,
            "reason": "cost burden dominates gross movement in sampled buckets",
        }
    if classification == CLASS_CONTAMINATED:
        return {
            "next_step": "discard_evidence_and_repeat_clean_paper",
            "patch_runtime": False,
            "patch_strategy": False,
            "reason": "contaminated evidence cannot support profitability search",
        }
    if classification == CLASS_TELEMETRY_GAP:
        return {
            "next_step": "telemetry_only_gap_repair",
            "patch_runtime": False,
            "patch_strategy": False,
            "reason": "core net/gross/cost fields missing",
        }
    return {
        "next_step": "new_stronger_alpha_design_required",
        "patch_runtime": False,
        "patch_strategy": False,
        "reason": "no bucket balances frequency, win rate, payoff size, and cost burden sufficiently",
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Profitability Operating Point Audit",
        "",
        f"- classification: `{report['classification']}`",
        f"- trajectory_event_count: `{report['summary']['trajectory_event_count']}`",
        f"- clean_event_count: `{report['summary']['clean_event_count']}`",
        f"- contaminated_event_count: `{report['summary']['contaminated_event_count']}`",
        f"- bucket_count: `{report['summary']['bucket_count']}`",
        f"- passing_bucket_count: `{report['summary']['passing_bucket_count']}`",
        f"- position_open_count: `{report['summary']['position_open_count']}`",
        f"- profitability_claim: `{report['profitability_claim']}`",
        f"- next_step: `{report['decision']['next_step']}`",
        "",
        "## Objective",
    ]
    for key, value in report["objective"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Best Operating Point"])
    if report["best_operating_point"] is None:
        lines.append("- none")
    else:
        row = report["best_operating_point"]
        lines.append(
            "- `{candidate}` samples=`{samples}` win_rate=`{win}` payoff=`{payoff}` expectancy=`{expectancy}` cost_to_gross=`{cost}`".format(
                candidate=row["candidate_key"],
                samples=row["sample_count"],
                win=row["win_rate"],
                payoff=row["payoff_ratio"],
                expectancy=row["expectancy_per_signal"],
                cost=row["cost_to_gross_ratio"],
            )
        )
    lines.extend(["", "## Ranked Buckets"])
    for row in report["ranked_buckets"][:15]:
        lines.append(
            "- `{candidate}` samples=`{samples}` win_rate=`{win}` payoff=`{payoff}` expectancy=`{expectancy}` p95=`{p95}` pass=`{passes}`".format(
                candidate=row["candidate_key"],
                samples=row["sample_count"],
                win=row["win_rate"],
                payoff=row["payoff_ratio"],
                expectancy=row["expectancy_per_signal"],
                p95=row["p95_signed_net"],
                passes=row["passes_operating_point"],
            )
        )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-artifact", default="analysis/stronger_alpha_observation_runtime_20260604_121000.json")
    parser.add_argument("--blocker-artifact", default="analysis/stronger_alpha_observation_blockers_20260604_121000.json")
    parser.add_argument("--output-json", default="analysis/profitability_operating_point_current.json")
    parser.add_argument("--output-md", default="analysis/profitability_operating_point_current.md")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = audit_operating_point(WORKDIR / args.runtime_artifact, WORKDIR / args.blocker_artifact)
    output_json = WORKDIR / args.output_json
    output_md = WORKDIR / args.output_md
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    output_md.write_text(render_markdown(report), encoding="utf-8")
    print(report["classification"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
