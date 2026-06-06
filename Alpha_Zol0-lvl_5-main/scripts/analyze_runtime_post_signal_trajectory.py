from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from statistics import mean
from typing import Any


WORKDIR = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = WORKDIR / "analysis"
EVENT_NAME = "post_signal_trajectory_v2"
RUNTIME_SOURCE = "rolling_quote_window"
STRONGER_FAMILIES = {"MICROBREAKOUT", "MOMENTUM", "MEANREVERSION"}
BASELINE_FAMILIES = {"TRENDFOLLOWING"}

CLASS_TARGETS = "POST_SIGNAL_TRAJECTORY_ALPHA_TARGETS_FOUND"
CLASS_NONE = "POST_SIGNAL_TRAJECTORY_NO_TARGETS"
CLASS_GAP = "POST_SIGNAL_TRAJECTORY_BLOCKED_BY_TELEMETRY_GAP"
CLASS_CONTAMINATED = "POST_SIGNAL_TRAJECTORY_EVIDENCE_CONTAMINATED"

CONTAMINATION_KEYS = ("seed", "fallback", "mock", "force_open", "forced_cycle")


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


def _load_payloads(db_path: Path) -> list[dict[str, Any]]:
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
        select_cols = [event_col, details_col]
        if timestamp_col:
            select_cols.append(timestamp_col)
        payloads: list[dict[str, Any]] = []
        for row in conn.execute(f"SELECT {', '.join(select_cols)} FROM logs ORDER BY rowid ASC"):
            values = dict(zip(select_cols, row))
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


def _normalize(payload: dict[str, Any]) -> dict[str, Any]:
    canonical = canonical_strategy(payload.get("canonical_strategy") or payload.get("strategy"))
    signed_net = _safe_float(payload.get("signed_net_move"))
    return {
        "db_path": payload.get("db_path"),
        "db_timestamp": payload.get("db_timestamp"),
        "symbol": str(payload.get("symbol") or "").upper(),
        "strategy": payload.get("strategy"),
        "canonical_strategy": canonical,
        "side": str(payload.get("side") or "").lower(),
        "source": payload.get("source"),
        "runtime_profile_key": payload.get("runtime_profile_key"),
        "horizon_ticks": _safe_int(payload.get("horizon_ticks"), 0),
        "signed_gross_move": _safe_float(payload.get("signed_gross_move")),
        "estimated_cost": _safe_float(payload.get("estimated_cost")),
        "signed_net_move": signed_net,
        "expected_move": _safe_float(payload.get("expected_move")),
        "expected_net_after_cost": _safe_float(payload.get("expected_net_after_cost")),
        "reason_code": payload.get("reason_code"),
        "contaminated": _is_contaminated(payload),
        "contamination_flags": payload.get("contamination_flags") if isinstance(payload.get("contamination_flags"), dict) else {},
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _family_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str, str, int], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            str(row.get("canonical_strategy")),
            str(row.get("symbol")),
            str(row.get("side")),
            _safe_int(row.get("horizon_ticks"), 0),
        )
        buckets.setdefault(key, []).append(row)
    summaries = []
    for (family, symbol, side, horizon), bucket in buckets.items():
        values = [
            float(row["signed_net_move"])
            for row in bucket
            if _safe_float(row.get("signed_net_move")) is not None
        ]
        summaries.append(
            {
                "canonical_strategy": family,
                "symbol": symbol,
                "side": side,
                "horizon_ticks": horizon,
                "sample_count": len(values),
                "mean_signed_net_move": float(mean(values)) if values else None,
                "p95_signed_net_move": _percentile(values, 0.95),
                "max_signed_net_move": max(values) if values else None,
            }
        )
    summaries.sort(
        key=lambda row: (
            _safe_float(row.get("p95_signed_net_move")) or -999.0,
            _safe_int(row.get("sample_count"), 0),
        ),
        reverse=True,
    )
    return summaries


def analyze_db_paths(
    db_paths: list[Path],
    *,
    min_samples: int = 20,
    min_p95_signed_net: float = 0.12,
) -> dict[str, Any]:
    raw = [payload for path in db_paths for payload in _load_payloads(Path(path))]
    rows = [_normalize(payload) for payload in raw]
    contaminated_rows = [row for row in rows if row["contaminated"]]
    clean_rows = [
        row
        for row in rows
        if not row["contaminated"]
        and row.get("source") == RUNTIME_SOURCE
        and _safe_float(row.get("signed_net_move")) is not None
    ]
    family_rows = _family_summary(clean_rows)
    alpha_targets = [
        row
        for row in family_rows
        if row["canonical_strategy"] in STRONGER_FAMILIES
        and row["sample_count"] >= int(min_samples)
        and (_safe_float(row.get("p95_signed_net_move")) or -999.0) >= float(min_p95_signed_net)
    ]
    baseline = [
        row
        for row in family_rows
        if row["canonical_strategy"] in BASELINE_FAMILIES
    ]
    if not rows:
        classification = CLASS_GAP
    elif contaminated_rows:
        classification = CLASS_CONTAMINATED
    elif alpha_targets:
        classification = CLASS_TARGETS
    else:
        classification = CLASS_NONE
    return {
        "classification": classification,
        "inputs": {
            "db_paths": [str(path) for path in db_paths],
            "min_samples": int(min_samples),
            "min_p95_signed_net": float(min_p95_signed_net),
            "runtime_source_required": RUNTIME_SOURCE,
        },
        "summary": {
            "db_count": len(db_paths),
            "trajectory_event_count": len(rows),
            "clean_event_count": len(clean_rows),
            "contaminated_event_count": len(contaminated_rows),
            "family_bucket_count": len(family_rows),
            "alpha_target_count": len(alpha_targets),
        },
        "alpha_targets": alpha_targets,
        "baseline_candidates": baseline,
        "ranked_family_buckets": family_rows,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Runtime Post-Signal Trajectory",
        "",
        f"- classification: `{report['classification']}`",
        f"- db_count: `{summary['db_count']}`",
        f"- trajectory_event_count: `{summary['trajectory_event_count']}`",
        f"- clean_event_count: `{summary['clean_event_count']}`",
        f"- contaminated_event_count: `{summary['contaminated_event_count']}`",
        f"- alpha_target_count: `{summary['alpha_target_count']}`",
        "",
        "## Alpha Targets",
    ]
    for row in report["alpha_targets"][:20]:
        lines.append(
            "- `{strategy}:{symbol}:{side}:h{horizon}` samples=`{samples}` p95=`{p95}` mean=`{mean}`".format(
                strategy=row["canonical_strategy"],
                symbol=row["symbol"],
                side=row["side"],
                horizon=row["horizon_ticks"],
                samples=row["sample_count"],
                p95=row["p95_signed_net_move"],
                mean=row["mean_signed_net_move"],
            )
        )
    if not report["alpha_targets"]:
        lines.append("- none")
    lines.append("")
    lines.append("## Ranked Buckets")
    for row in report["ranked_family_buckets"][:20]:
        lines.append(
            "- `{strategy}:{symbol}:{side}:h{horizon}` samples=`{samples}` p95=`{p95}` max=`{max_value}`".format(
                strategy=row["canonical_strategy"],
                symbol=row["symbol"],
                side=row["side"],
                horizon=row["horizon_ticks"],
                samples=row["sample_count"],
                p95=row["p95_signed_net_move"],
                max_value=row["max_signed_net_move"],
            )
        )
    return "\n".join(lines) + "\n"


def _resolve_db_paths(root: Path, db_glob: str, max_dbs: int, explicit_dbs: list[str]) -> list[Path]:
    paths = [Path(db_path) for db_path in explicit_dbs]
    if db_glob:
        paths.extend(sorted((root / "tmp").glob(db_glob), key=lambda p: p.stat().st_mtime, reverse=True))
    unique = []
    seen = set()
    for path in paths:
        resolved = path if path.is_absolute() else root / path
        key = str(resolved)
        if key not in seen and resolved.exists():
            seen.add(key)
            unique.append(resolved)
    return unique[:max_dbs]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", action="append", default=[])
    parser.add_argument("--db-glob", default="controlled_kpi_after_*.db")
    parser.add_argument("--max-dbs", type=int, default=30)
    parser.add_argument("--min-samples", type=int, default=20)
    parser.add_argument("--min-p95-signed-net", type=float, default=0.12)
    parser.add_argument("--output-json", default="analysis/runtime_post_signal_trajectory_current.json")
    parser.add_argument("--output-md", default="analysis/runtime_post_signal_trajectory_current.md")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_paths = _resolve_db_paths(WORKDIR, args.db_glob, args.max_dbs, args.db)
    report = analyze_db_paths(
        db_paths,
        min_samples=args.min_samples,
        min_p95_signed_net=args.min_p95_signed_net,
    )
    output_json = WORKDIR / args.output_json
    output_md = WORKDIR / args.output_md
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    output_md.write_text(render_markdown(report), encoding="utf-8")
    print(report["classification"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
