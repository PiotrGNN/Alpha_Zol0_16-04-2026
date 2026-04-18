from __future__ import annotations

import json
import math
import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from new_proxy_validation import (
    ANALYSIS,
    AUTOPSY,
    DecisionEval,
    _extract_seed_from_path,
    _match_linkage_evidence,
    _link_outcomes,
    _load_json,
    _load_position_closes,
    _load_position_opens,
    _safe_float,
)
from profitability_total_cost_audit import _extract_run_metrics


ROOT = Path(__file__).resolve().parents[1]
RUN_SCRIPT = ROOT / "DataAnalysisExpert" / "phase4b_run_seed.ps1"
BOTCORE_PATH = ROOT / "Alpha_Zol0-lvl_5-main" / "core" / "BotCore.py"
DEFAULT_SCANNER_OUTPUT = ROOT / "data" / "top_scalping_pairs.json"

DEFAULT_ARTIFACT_PREFIX = "phase94_shadow_promotion_pipeline"
RUN_SPEC_PROFILES: dict[str, tuple[tuple[int, int], ...]] = {
    "readiness_default": ((2024, 720), (9001, 720)),
    "rca_matched": ((126, 720), (1337, 720)),
}
DEFAULT_RUN_SPEC_PROFILE = "readiness_default"
DEFAULT_RUN_SPECS = RUN_SPEC_PROFILES[DEFAULT_RUN_SPEC_PROFILE]
FORMULA_PROVENANCE_JSON = ANALYSIS / "execution_cost_formula_provenance.json"
FORMULA_PROVENANCE_MD = ANALYSIS / "execution_cost_formula_provenance.md"
DEFAULT_RECOVERY_TICKS_PER_RUN = 1440
DEFAULT_RECOVERY_THRESHOLDS = "0.0015,0.0036,0.0038,0.005,0.01,0.015"
PHASE95_ARTIFACT_PREFIX = "phase95_parallel_scanner_top100_top20_validation_medium"
PHASE95_BASELINE_STAMP = "20260317_092846"
PHASE95_FRESH_STAMP = "20260317_092953"

MIN_FRESH_DB_COUNT = 2
MIN_HISTORY_READY_ROWS = 300
MIN_ADMITTED_ROWS = 4
MIN_ADMITTED_NEAR_THRESHOLD_ROWS = 2
MIN_LINKED_CLOSES = 2
MIN_LINKED_NEAR_THRESHOLD_ROWS = 2

NEAR_THRESHOLD_ALLOWED_BUCKET = "[0,0.001)"
BROAD_NEAR_THRESHOLD_BUCKETS = {
    "[-0.001,-0.0005)",
    "[-0.0005,0)",
    "[0,0.001)",
    "[0.001,0.002)",
}
FLOAT_TOLERANCE = 1e-9

ALLOWED_VERDICTS = {
    "HOLD_FOR_MORE_DATA",
    "DO_NOT_PROMOTE",
    "PREPARE_DISABLED_FLAG_PATCH",
}


@dataclass(frozen=True)
class RunSpec:
    seed: int
    ticks_per_run: int
    tick_sleep_sec: float = 1.0


@dataclass(frozen=True)
class FreshArtifacts:
    seed: int
    db_path: Path
    result_json: Path
    fee_json: Path
    calibration_json: Path
    stdout_log: Path
    stderr_log: Path
    wrapper_log: Path


@dataclass(frozen=True)
class DecisionRow:
    db_path: Path
    decision_rowid: int
    timestamp: datetime
    symbol: str | None
    side: str | None
    mr_pocket_symbol: str | None
    mr_pocket_side: str | None
    mr_pocket_regime: str | None
    mr_pocket_atr_bucket: str | None
    mr_pocket_score_bucket: str | None
    mr_pocket_tuple: str | None
    mr_gate_action: str | None
    mr_gate_reason: str | None
    mr_gate_runtime_decision_unchanged: bool | None
    raw_decision: str | None
    final_decision: str | None
    entry_reason: str | None
    candidate_history_ready: bool
    candidate_proxy_value: float | None
    candidate_expected_edge_after_fee: float | None
    candidate_router_lead: float | None
    edge_history_ready: bool
    bucket_source: str | None
    trade_count: int | None
    trade_count_primary: int | None
    trade_count_fallback: int | None
    strategy: str | None
    current_mean_gross_fill_model: float | None
    current_mean_fee_total: float | None
    current_edge_over_fee_value: float | None
    active_threshold: float | None
    current_margin_to_threshold: float | None
    shadow_spread_slippage_proxy: float | None
    shadow_execution_cost_total: float | None
    shadow_edge_after_execution_cost: float | None
    shadow_margin_to_threshold: float | None
    current_gate_blocked: bool
    shadow_gate_blocked: bool
    shadow_counterfactual_raw: bool | None
    shadow_counterfactual_history_gated: bool | None
    shadow_counterfactual_history_exclusion_reason: str | None
    shadow_counterfactual_forensic_class: str | None
    mr_features: dict[str, Any] | None
    mr_shadow_rule_pass: bool | None
    mr_shadow_rule_reject_reason: str | None
    mr_shadow_rule_thresholds: dict[str, Any] | None
    mr_shadow_rule_checks: dict[str, Any] | None
    mr_shadow_rule_variant: str | None
    realtime_execution_snapshot: dict[str, Any] | None
    realtime_edge_diagnostic: dict[str, Any] | None
    live_edge_status: dict[str, Any] | None


@dataclass
class StageRecorder:
    name: str
    checks: list[dict[str, Any]]
    issues: list[str]
    warnings: list[str]

    def __init__(self, name: str) -> None:
        self.name = name
        self.checks = []
        self.issues = []
        self.warnings = []

    def check(
        self,
        description: str,
        passed: bool,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.checks.append(
            {
                "description": description,
                "passed": bool(passed),
                "details": details or {},
            }
        )
        if not passed:
            self.issues.append(description)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def finalize(self) -> dict[str, Any]:
        return {
            "stage": self.name,
            "passed": not self.issues,
            "issue_count": len(self.issues),
            "warning_count": len(self.warnings),
            "issues": self.issues,
            "warnings": self.warnings,
            "checks": self.checks,
        }


def default_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def selection_timestamp() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def parse_run_specs(
    values: list[str],
    profile: str = DEFAULT_RUN_SPEC_PROFILE,
) -> list[RunSpec]:
    if not values:
        profile_values = RUN_SPEC_PROFILES.get(str(profile or "").strip())
        if not profile_values:
            raise ValueError(
                "Unknown run spec profile: "
                f"{profile}. Available profiles: "
                f"{', '.join(sorted(RUN_SPEC_PROFILES))}"
            )
        return [
            RunSpec(seed=seed, ticks_per_run=ticks)
            for seed, ticks in profile_values
        ]
    out: list[RunSpec] = []
    for value in values:
        parts = [part.strip() for part in str(value).split(":") if part.strip()]
        if len(parts) < 2:
            raise ValueError(f"Invalid run spec: {value}")
        sleep_sec = float(parts[2]) if len(parts) >= 3 else 1.0
        out.append(
            RunSpec(
                seed=int(parts[0]),
                ticks_per_run=int(parts[1]),
                tick_sleep_sec=float(sleep_sec),
            )
        )
    return out


def _round_float(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except Exception:
        return None
    if not math.isfinite(number):
        return None
    return round(number, 10)


def _mean(values: list[float | None]) -> float | None:
    valid = [float(value) for value in values if isinstance(value, (int, float))]
    if not valid:
        return None
    return float(sum(valid)) / float(len(valid))


def _parse_db_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(value), fmt)
        except Exception:
            continue
    return None


def _normalize_side(value: Any) -> str | None:
    side = str(value or "").strip().lower()
    if side in {"buy", "long"}:
        return "buy"
    if side in {"sell", "short"}:
        return "sell"
    return None


def _normalize_db_path_for_compare(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        path = Path(raw).resolve(strict=False)
        return os.path.normcase(os.path.normpath(str(path)))
    except Exception:
        return os.path.normcase(os.path.normpath(raw))


def _margin_bucket(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value < -0.005:
        return "lt_-0.005"
    if value < -0.002:
        return "[-0.005,-0.002)"
    if value < -0.001:
        return "[-0.002,-0.001)"
    if value < -0.0005:
        return "[-0.001,-0.0005)"
    if value < 0.0:
        return "[-0.0005,0)"
    if value < 0.001:
        return "[0,0.001)"
    if value < 0.002:
        return "[0.001,0.002)"
    return ">=0.002"


def _is_admitted_near_threshold_bucket(
    current_bucket: str | None,
    shadow_bucket: str | None,
) -> bool:
    return (
        current_bucket == NEAR_THRESHOLD_ALLOWED_BUCKET
        or shadow_bucket == NEAR_THRESHOLD_ALLOWED_BUCKET
    )


def _is_broad_near_threshold_bucket(
    current_bucket: str | None,
    shadow_bucket: str | None,
) -> bool:
    return (
        current_bucket in BROAD_NEAR_THRESHOLD_BUCKETS
        or shadow_bucket in BROAD_NEAR_THRESHOLD_BUCKETS
    )


def _shadow_effect_alignment(
    primary_fail_subset_size: int,
    secondary_effect_size: int,
) -> str:
    return (
        "ALIGNED"
        if int(primary_fail_subset_size) == int(secondary_effect_size)
        else "MISALIGNED"
    )


def _nearest_threshold_distance(row: dict[str, Any]) -> float | None:
    values = [
        abs(value)
        for value in (
            _safe_float(row.get("current_margin_to_threshold")),
            _safe_float(row.get("shadow_margin_to_threshold")),
        )
        if value is not None
    ]
    if not values:
        return None
    return min(values)


def _serialize_nearest_threshold_row(
    row: dict[str, Any],
    rank: int,
) -> dict[str, Any]:
    linked_close = row.get("linked_close") or {}
    return {
        "rank": rank,
        "seed": row.get("seed"),
        "decision_rowid": row.get("decision_rowid"),
        "timestamp": row.get("timestamp"),
        "strategy": row.get("strategy"),
        "trade_count": row.get("trade_count"),
        "bucket_source": row.get("bucket_source"),
        "runtime_history_ready": bool(row.get("runtime_history_ready")),
        "partial_history_ready": bool(row.get("partial_history_ready")),
        "linkage_eligible": bool(row.get("linkage_eligible")),
        "linked_close": bool(row.get("linked_close") is not None),
        "linked_trade_id": linked_close.get("trade_id"),
        "excluded_reason": row.get("excluded_reason"),
        "current_margin_to_threshold": row.get("current_margin_to_threshold"),
        "shadow_margin_to_threshold": row.get("shadow_margin_to_threshold"),
        "nearest_margin_distance": _round_float(_nearest_threshold_distance(row)),
        "current_margin_bucket": row.get("current_margin_bucket"),
        "shadow_margin_bucket": row.get("shadow_margin_bucket"),
        "current_edge_over_fee_value": row.get("current_edge_over_fee_value"),
        "shadow_edge_after_execution_cost": row.get(
            "shadow_edge_after_execution_cost"
        ),
    }


def _rank_nearest_threshold_rows(
    rows: list[dict[str, Any]],
    limit: int = 10,
) -> list[dict[str, Any]]:
    ranked: list[tuple[float, int, int, dict[str, Any]]] = []
    for row in rows:
        distance = _nearest_threshold_distance(row)
        if distance is None:
            continue
        ranked.append(
            (
                distance,
                int(row.get("seed") or -1),
                int(row.get("decision_rowid") or -1),
                row,
            )
        )
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    return [
        _serialize_nearest_threshold_row(row, rank=index + 1)
        for index, (_, _, _, row) in enumerate(ranked[:limit])
    ]


def _bucket_distribution(
    rows: list[dict[str, Any]],
    key_name: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(key_name) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return {
        key: counts[key]
        for key in sorted(counts, key=lambda item: (-counts[item], item))
    }


def _seed_stage_breakdown(admitted_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[int, dict[str, Any]] = {}
    for row in admitted_rows:
        seed = int(row.get("seed") or -1)
        entry = grouped.setdefault(
            seed,
            {
                "seed": seed,
                "admitted_rows": 0,
                "runtime_history_ready_rows": 0,
                "partial_history_ready_rows": 0,
                "linkage_eligible_rows": 0,
                "linked_rows": 0,
                "strict_near_threshold_rows": 0,
                "broad_near_threshold_rows": 0,
                "linked_near_threshold_rows": 0,
                "linked_broad_near_threshold_rows": 0,
            },
        )
        entry["admitted_rows"] += 1
        if bool(row.get("runtime_history_ready")):
            entry["runtime_history_ready_rows"] += 1
        if bool(row.get("partial_history_ready")):
            entry["partial_history_ready_rows"] += 1
        if bool(row.get("linkage_eligible")):
            entry["linkage_eligible_rows"] += 1
        linked = row.get("linked_close") is not None
        if linked:
            entry["linked_rows"] += 1
        strict = _is_admitted_near_threshold_bucket(
            row.get("current_margin_bucket"),
            row.get("shadow_margin_bucket"),
        )
        broad = _is_broad_near_threshold_bucket(
            row.get("current_margin_bucket"),
            row.get("shadow_margin_bucket"),
        )
        if strict:
            entry["strict_near_threshold_rows"] += 1
        if broad:
            entry["broad_near_threshold_rows"] += 1
        if linked and strict:
            entry["linked_near_threshold_rows"] += 1
        if linked and broad:
            entry["linked_broad_near_threshold_rows"] += 1
    return [grouped[key] for key in sorted(grouped)]


def _build_sample_diagnostics(
    *,
    row_level_audit: list[dict[str, Any]],
    admitted_rows: list[dict[str, Any]],
    linked_rows: list[dict[str, Any]],
    admitted_near_threshold_rows: list[dict[str, Any]],
    linked_near_threshold_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    broad_near_threshold_rows = [
        row
        for row in admitted_rows
        if _is_broad_near_threshold_bucket(
            row.get("current_margin_bucket"),
            row.get("shadow_margin_bucket"),
        )
    ]
    linked_broad_near_threshold_rows = [
        row
        for row in linked_rows
        if _is_broad_near_threshold_bucket(
            row.get("current_margin_bucket"),
            row.get("shadow_margin_bucket"),
        )
    ]
    linkage_eligible_rows = [
        row for row in admitted_rows if bool(row.get("linkage_eligible"))
    ]
    return {
        "stage_reduction": {
            "rows_audited": len(row_level_audit),
            "admitted_rows": len(admitted_rows),
            "linkage_eligible_rows": len(linkage_eligible_rows),
            "linked_rows": len(linked_rows),
            "strict_near_threshold_rows": len(admitted_near_threshold_rows),
            "broad_near_threshold_rows": len(broad_near_threshold_rows),
            "linked_near_threshold_rows": len(linked_near_threshold_rows),
            "linked_broad_near_threshold_rows": len(linked_broad_near_threshold_rows),
        },
        "bucket_distributions": {
            "admitted_current_margin_buckets": _bucket_distribution(
                admitted_rows,
                "current_margin_bucket",
            ),
            "admitted_shadow_margin_buckets": _bucket_distribution(
                admitted_rows,
                "shadow_margin_bucket",
            ),
            "linked_current_margin_buckets": _bucket_distribution(
                linked_rows,
                "current_margin_bucket",
            ),
            "linked_shadow_margin_buckets": _bucket_distribution(
                linked_rows,
                "shadow_margin_bucket",
            ),
        },
        "per_seed": _seed_stage_breakdown(admitted_rows),
        "nearest_to_threshold_admitted_rows": _rank_nearest_threshold_rows(
            admitted_rows
        ),
        "nearest_to_threshold_linked_rows": _rank_nearest_threshold_rows(linked_rows),
        "broad_near_threshold_admitted_rows": _rank_nearest_threshold_rows(
            broad_near_threshold_rows
        ),
        "broad_near_threshold_linked_rows": _rank_nearest_threshold_rows(
            linked_broad_near_threshold_rows
        ),
    }


def _derive_shadow_counterfactual_analysis_fields(
    *,
    shadow_edge_after_execution_cost: float | None,
    threshold: float | None,
    history_ready: bool,
    payload_raw: Any = None,
    payload_history_gated: Any = None,
    payload_exclusion_reason: Any = None,
    payload_forensic_class: Any = None,
) -> dict[str, Any]:
    raw_value: bool | None
    if payload_raw is None:
        if shadow_edge_after_execution_cost is None or threshold is None:
            raw_value = None
        else:
            raw_value = bool(
                float(shadow_edge_after_execution_cost) < float(threshold)
            )
    else:
        raw_value = bool(payload_raw)

    history_gated_value: bool | None
    if payload_history_gated is None:
        if raw_value is None:
            history_gated_value = None
        else:
            history_gated_value = bool(history_ready and raw_value)
    else:
        history_gated_value = bool(payload_history_gated)

    exclusion_reason = str(payload_exclusion_reason or "").strip() or None
    forensic_class = str(payload_forensic_class or "").strip() or None

    if exclusion_reason is None:
        if raw_value is None or history_gated_value is None:
            exclusion_reason = "unknown"
        elif raw_value and not history_ready:
            exclusion_reason = "history_not_ready"
        elif raw_value and history_ready:
            exclusion_reason = "passed_shadow_check"
        else:
            exclusion_reason = "threshold_not_breached"

    if forensic_class is None:
        if raw_value is None or history_gated_value is None:
            forensic_class = "insufficient_inputs"
        elif raw_value and not history_ready:
            forensic_class = "would_fail_if_history_ignored"
        elif raw_value and history_ready:
            forensic_class = "would_fail_and_history_ready"
        else:
            forensic_class = "would_pass_even_if_history_ignored"

    return {
        "shadow_counterfactual_raw": raw_value,
        "shadow_counterfactual_history_gated": history_gated_value,
        "shadow_counterfactual_history_exclusion_reason": exclusion_reason,
        "shadow_counterfactual_forensic_class": forensic_class,
    }


def _float_equal(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return abs(float(left) - float(right)) <= FLOAT_TOLERANCE


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _snapshot_float(snapshot: dict[str, Any] | None, key: str) -> float | None:
    if not isinstance(snapshot, dict):
        return None
    return _safe_float(snapshot.get(key))


def _extract_mr_features_from_payload(
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    explicit = payload.get("mr_features")
    if isinstance(explicit, dict):
        return explicit

    signal_groups: list[Any] = []
    for key in ("ensemble_signals_filtered", "ensemble_signals"):
        values = payload.get(key)
        if isinstance(values, list):
            signal_groups.extend(values)

    mr_signal: dict[str, Any] | None = None
    for item in signal_groups:
        if not isinstance(item, dict):
            continue
        strategy_name = str(item.get("strategy") or "").strip().lower()
        if strategy_name != "meanreversion":
            continue
        signal = item.get("signal")
        if isinstance(signal, dict):
            mr_signal = signal
            break
    if not isinstance(mr_signal, dict):
        return None

    metrics = mr_signal.get("metrics")
    analysis = mr_signal.get("analysis")
    if not isinstance(metrics, dict):
        metrics = {}
    if not isinstance(analysis, dict):
        analysis = {}

    price = _safe_float(metrics.get("price"))
    if price is None:
        price = _safe_float(metrics.get("current_price"))
    if price is None:
        price = _safe_float(analysis.get("current_price"))

    bb_lower = _safe_float(metrics.get("bb_lower"))
    bb_upper = _safe_float(metrics.get("bb_upper"))
    bb_width = _safe_float(metrics.get("bb_width"))
    if bb_width is None and bb_lower is not None and bb_upper is not None:
        bb_width = float(bb_upper) - float(bb_lower)

    std = _safe_float(metrics.get("std"))
    if std is None:
        std = _safe_float(analysis.get("std"))

    price_dist_to_bb_lower_pct = _safe_float(
        metrics.get("price_dist_to_bb_lower_pct")
    )
    if (
        price_dist_to_bb_lower_pct is None
        and price is not None
        and bb_lower is not None
        and float(price) != 0.0
    ):
        price_dist_to_bb_lower_pct = (
            float(price) - float(bb_lower)
        ) / float(price)

    price_dist_to_bb_lower_std = _safe_float(
        metrics.get("price_dist_to_bb_lower_std")
    )
    if (
        price_dist_to_bb_lower_std is None
        and price is not None
        and bb_lower is not None
        and std is not None
        and float(std) != 0.0
    ):
        price_dist_to_bb_lower_std = (
            float(price) - float(bb_lower)
        ) / float(std)

    values = {
        "rsi": _safe_float(metrics.get("rsi")),
        "bb_lower": bb_lower,
        "bb_upper": bb_upper,
        "bb_width": bb_width,
        "price": price,
        "price_dist_to_bb_lower_pct": price_dist_to_bb_lower_pct,
        "price_dist_to_bb_lower_std": price_dist_to_bb_lower_std,
    }
    if not any(value is not None for value in values.values()):
        return None
    return values


def _execution_cost_diagnostic_json_path(artifact_prefix: str, stamp: str) -> Path:
    return AUTOPSY / f"{artifact_prefix}_{stamp}_execution_cost_diagnostic.json"


def _execution_cost_diagnostic_md_path(artifact_prefix: str, stamp: str) -> Path:
    return AUTOPSY / f"{artifact_prefix}_{stamp}_execution_cost_diagnostic.md"


def _scanner_rankings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("top_scalping_pairs")
    if isinstance(rows, list) and rows:
        return [row for row in rows if isinstance(row, dict)]
    rows = payload.get("pairs")
    if isinstance(rows, list) and rows:
        return [row for row in rows if isinstance(row, dict)]
    return []


def _scanner_symbol_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for value in values:
        if isinstance(value, dict):
            symbol = str(value.get("symbol") or "").strip().upper()
        else:
            symbol = str(value or "").strip().upper()
        if not symbol or symbol in out:
            continue
        out.append(symbol)
    return out


def serialize_artifacts(artifacts: list[FreshArtifacts]) -> list[dict[str, Any]]:
    return [
        {
            "seed": artifact.seed,
            "db_path": str(artifact.db_path),
            "result_json": str(artifact.result_json),
            "fee_json": str(artifact.fee_json),
            "calibration_json": str(artifact.calibration_json),
            "stdout_log": str(artifact.stdout_log),
            "stderr_log": str(artifact.stderr_log),
            "wrapper_log": str(artifact.wrapper_log),
        }
        for artifact in artifacts
    ]


def _extract_ticks_per_run_from_wrapper_log(wrapper_log: Path) -> int:
    if not wrapper_log.exists():
        return DEFAULT_RECOVERY_TICKS_PER_RUN
    text = wrapper_log.read_text(encoding="utf-8", errors="ignore")
    marker = "ticks="
    if marker not in text:
        return DEFAULT_RECOVERY_TICKS_PER_RUN
    suffix = text.split(marker, 1)[1]
    digits = []
    for char in suffix:
        if char.isdigit():
            digits.append(char)
        else:
            break
    if not digits:
        return DEFAULT_RECOVERY_TICKS_PER_RUN
    try:
        return max(1, int("".join(digits)))
    except Exception:
        return DEFAULT_RECOVERY_TICKS_PER_RUN


def _build_fallback_result_payload(
    artifact: FreshArtifacts,
    ticks_per_run: int,
) -> dict[str, Any]:
    conn = sqlite3.connect(str(artifact.db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        decision_count = int(
            (cur.execute("SELECT COUNT(*) FROM decisions").fetchone() or [0])[0]
            or 0
        )
        log_count = int(
            (cur.execute("SELECT COUNT(*) FROM logs").fetchone() or [0])[0] or 0
        )
        position_opens = 0
        position_closes = 0
        orders_simulated = 0
        closes_buy = 0
        closes_sell = 0
        closes_unknown = 0
        closed_pnl_buy = 0.0
        closed_pnl_sell = 0.0
        closed_realized_pnl = 0.0
        allocations: list[float] = []

        for event, details in cur.execute(
            "SELECT event, details FROM logs ORDER BY rowid"
        ):
            payload = _load_json(details)
            if event == "position_open":
                position_opens += 1
                continue
            if event == "order_simulated":
                orders_simulated += 1
                continue
            if event == "risk_decision":
                allocation = payload.get("allocation")
                if isinstance(allocation, (int, float)):
                    allocations.append(float(allocation))
                continue
            if event != "position_close":
                continue
            position_closes += 1
            pnl = payload.get("realized_pnl")
            if isinstance(pnl, (int, float)):
                closed_realized_pnl += float(pnl)
            position = payload.get("position")
            position = position if isinstance(position, dict) else {}
            side = str(
                position.get("side")
                or position.get("position_side")
                or position.get("direction")
                or ""
            ).strip().lower()
            if side in {"long", "buy"}:
                closes_buy += 1
                if isinstance(pnl, (int, float)):
                    closed_pnl_buy += float(pnl)
            elif side in {"short", "sell"}:
                closes_sell += 1
                if isinstance(pnl, (int, float)):
                    closed_pnl_sell += float(pnl)
            else:
                closes_unknown += 1

        last_decision = None
        row = cur.execute(
            "SELECT rowid, * FROM decisions ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        if row is not None:
            last_decision = {key: row[key] for key in row.keys()}
    finally:
        conn.close()

    avg_allocation = (
        round(sum(allocations) / len(allocations), 4) if allocations else 0
    )
    return {
        "generated_at_utc": datetime.now().astimezone().isoformat(),
        "summary_source": "fallback_db",
        "summary_reason": "auto_recovered_missing_runner_summary",
        "total_runs": 1,
        "ticks_per_run": int(ticks_per_run),
        "db_path": str(artifact.db_path),
        "ok_runs": 1 if decision_count or log_count or position_closes else 0,
        "error_runs": 0,
        "runner_exit_code": 0,
        "total_elapsed_sec": None,
        "total_trades": position_closes,
        "total_net_pnl": round(closed_realized_pnl, 6),
        "total_position_closes": position_closes,
        "total_closes_buy": closes_buy,
        "total_closes_sell": closes_sell,
        "total_closed_pnl_buy": round(closed_pnl_buy, 6),
        "total_closed_pnl_sell": round(closed_pnl_sell, 6),
        "avg_allocation_usdt": avg_allocation,
        "runs": [
            {
                "run": 1,
                "ticks": int(ticks_per_run),
                "elapsed_sec": None,
                "trades": position_closes,
                "net_pnl": round(closed_realized_pnl, 6),
                "position_opens": position_opens,
                "position_closes": position_closes,
                "orders_simulated": orders_simulated,
                "closed_realized_pnl_from_logs": round(closed_realized_pnl, 6),
                "closes_buy": closes_buy,
                "closes_sell": closes_sell,
                "closes_unknown": closes_unknown,
                "closed_pnl_buy": round(closed_pnl_buy, 6),
                "closed_pnl_sell": round(closed_pnl_sell, 6),
                "allocation": avg_allocation,
                "decisions_count": decision_count,
                "log_count": log_count,
                "last_decision": last_decision,
                "status": "fallback_db",
            }
        ],
    }


def _recover_missing_artifact_sidecars(artifacts: list[FreshArtifacts]) -> None:
    fee_reporter = ROOT / "DataAnalysisExpert" / "report_fee_sanity.py"
    replay_harness = ROOT / "DataAnalysisExpert" / "replay_entry_live_edge_state.py"
    for artifact in artifacts:
        if artifact.db_path.exists() and not artifact.result_json.exists():
            ticks_per_run = _extract_ticks_per_run_from_wrapper_log(
                artifact.wrapper_log
            )
            payload = _build_fallback_result_payload(artifact, ticks_per_run)
            artifact.result_json.write_text(
                json.dumps(payload, indent=2, default=str),
                encoding="utf-8",
            )
        if artifact.db_path.exists() and not artifact.fee_json.exists():
            subprocess.run(
                [
                    sys.executable,
                    str(fee_reporter),
                    "--db",
                    str(artifact.db_path),
                    "--out-json",
                    str(artifact.fee_json),
                ],
                cwd=str(ROOT),
                check=True,
            )
        if artifact.db_path.exists() and not artifact.calibration_json.exists():
            subprocess.run(
                [
                    sys.executable,
                    str(replay_harness),
                    "--db",
                    str(artifact.db_path),
                    "--thresholds",
                    DEFAULT_RECOVERY_THRESHOLDS,
                    "--out-json",
                    str(artifact.calibration_json),
                ],
                cwd=str(ROOT),
                check=True,
            )


def run_seed_batch(
    run_spec: RunSpec,
    artifact_prefix: str,
    stamp: str,
    python_exe: str,
    run_symbols: list[str] | None = None,
    entry_meanreversion_enable: str | None = None,
) -> FreshArtifacts:
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(RUN_SCRIPT),
        "-Seed",
        str(run_spec.seed),
        "-TicksPerRun",
        str(run_spec.ticks_per_run),
        "-TickSleepSec",
        str(run_spec.tick_sleep_sec),
        "-ArtifactPrefix",
        artifact_prefix,
        "-Stamp",
        stamp,
        "-Root",
        str(ROOT),
        "-PythonExe",
        python_exe,
    ]
    if run_symbols:
        command.extend(["-RunSymbols", ",".join(run_symbols)])
    env = os.environ.copy()
    if entry_meanreversion_enable in {"0", "1"}:
        env["ENTRY_MEANREVERSION_ENABLE"] = entry_meanreversion_enable
    subprocess.run(command, check=True, cwd=str(ROOT), env=env)
    base = f"{artifact_prefix}_seed{run_spec.seed}_{stamp}"
    return FreshArtifacts(
        seed=run_spec.seed,
        db_path=AUTOPSY / f"{base}_paper_v2.db",
        result_json=AUTOPSY / f"{base}_paper_v2_results.json",
        fee_json=AUTOPSY / f"{base}_fee_sanity.json",
        calibration_json=AUTOPSY / f"{base}_entry_live_edge_calibration.json",
        stdout_log=AUTOPSY / f"{base}.out.log",
        stderr_log=AUTOPSY / f"{base}.err.log",
        wrapper_log=AUTOPSY / f"{base}.wrapper.log",
    )


def build_fresh_validation_batch(
    run_specs: list[RunSpec],
    artifact_prefix: str,
    stamp: str,
    python_exe: str,
    run_symbols: list[str] | None = None,
    scanner_output_path: str | None = None,
    scanner_top_n: int = 0,
    entry_meanreversion_enable: str | None = None,
) -> dict[str, Any]:
    selected_symbols_context = resolve_selected_symbols(
        artifact_prefix=artifact_prefix,
        stamp=stamp,
        run_symbols=run_symbols,
        scanner_output_path=scanner_output_path,
        scanner_top_n=scanner_top_n,
    )
    effective_run_symbols = selected_symbols_context.get("selected_symbols") or None
    artifacts = [
        run_seed_batch(
            run_spec=run_spec,
            artifact_prefix=artifact_prefix,
            stamp=stamp,
            python_exe=python_exe,
            run_symbols=effective_run_symbols,
            entry_meanreversion_enable=entry_meanreversion_enable,
        )
        for run_spec in run_specs
    ]
    expected_seeds = {run_spec.seed for run_spec in run_specs}
    discovered, discovery_meta = discover_fresh_artifacts(
        artifact_prefix=artifact_prefix,
        stamp=stamp,
        expected_seeds=expected_seeds,
    )
    return {
        "artifacts": artifacts,
        "fresh_artifacts": discovered,
        "discovery_meta": discovery_meta,
        "selected_symbols_context": selected_symbols_context,
    }


def _selected_symbols_artifact_path(artifact_prefix: str, stamp: str) -> Path:
    return AUTOPSY / f"{artifact_prefix}_{stamp}_selected_symbols.json"


def _load_scanner_selected_symbols(
    scanner_output_path: Path,
    top_n: int,
) -> dict[str, Any]:
    if top_n <= 0:
        raise ValueError("scanner_top_n must be greater than zero")
    if not scanner_output_path.exists():
        raise FileNotFoundError(f"Scanner output not found: {scanner_output_path}")
    payload = _load_json(scanner_output_path.read_text(encoding="utf-8"))
    pairs = _scanner_rankings(payload)
    if not pairs:
        raise ValueError("Scanner output does not contain ranked symbol rows")
    keep_symbols = _scanner_symbol_list(payload.get("keep"))
    watch_symbols = _scanner_symbol_list(payload.get("watch"))
    drop_symbols = set(_scanner_symbol_list(payload.get("drop")))
    selected_symbols: list[str] = []
    if keep_symbols or watch_symbols or drop_symbols:
        for symbol in keep_symbols:
            if symbol in drop_symbols or symbol in selected_symbols:
                continue
            selected_symbols.append(symbol)
            if len(selected_symbols) >= top_n:
                break
        watch_added = 0
        for symbol in watch_symbols:
            if len(selected_symbols) >= top_n or watch_added >= 2:
                break
            if symbol in drop_symbols or symbol in selected_symbols:
                continue
            selected_symbols.append(symbol)
            watch_added += 1
    if not selected_symbols:
        for pair in pairs:
            symbol = str(pair.get("symbol") or "").strip().upper()
            if not symbol or symbol in selected_symbols or symbol in drop_symbols:
                continue
            selected_symbols.append(symbol)
            if len(selected_symbols) >= top_n:
                break
    if not selected_symbols:
        raise ValueError("Scanner output did not yield any valid symbols")
    return {
        "timestamp": selection_timestamp(),
        "source": str(payload.get("source") or "volatility_rotation"),
        "selected_symbols": selected_symbols,
        "selection_method": "scanner_top_n",
        "scanner_top_n": int(top_n),
        "scanner_output_path": str(scanner_output_path),
        "scanner_generated_at": payload.get("generated_at") or payload.get("timestamp"),
        "excluded_symbols": (
            payload.get("excluded_symbols") or payload.get("skipped") or []
        ),
        "ranked_snapshot": pairs[:top_n],
    }


def _write_selected_symbols_artifact(
    artifact_prefix: str,
    stamp: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    artifact_path = _selected_symbols_artifact_path(artifact_prefix, stamp)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    out = dict(payload)
    out["artifact_path"] = str(artifact_path)
    out["exists"] = True
    return out


def resolve_selected_symbols(
    artifact_prefix: str,
    stamp: str,
    run_symbols: list[str] | None = None,
    scanner_output_path: str | None = None,
    scanner_top_n: int = 0,
) -> dict[str, Any]:
    artifact_path = _selected_symbols_artifact_path(artifact_prefix, stamp)
    if run_symbols:
        return _write_selected_symbols_artifact(
            artifact_prefix,
            stamp,
            {
                "timestamp": selection_timestamp(),
                "source": "manual-run-symbols",
                "selected_symbols": list(run_symbols),
                "selection_method": "explicit_run_symbols",
                "scanner_top_n": None,
                "scanner_output_path": None,
            },
        )
    if scanner_top_n > 0:
        scanner_path = (
            Path(scanner_output_path)
            if scanner_output_path
            else DEFAULT_SCANNER_OUTPUT
        )
        payload = _load_scanner_selected_symbols(scanner_path, scanner_top_n)
        return _write_selected_symbols_artifact(artifact_prefix, stamp, payload)
    return {
        "timestamp": None,
        "source": None,
        "selected_symbols": [],
        "selection_method": "default_wrapper_symbols",
        "scanner_top_n": None,
        "scanner_output_path": None,
        "artifact_path": str(artifact_path),
        "exists": False,
    }


def discover_selected_symbols_context(
    artifact_prefix: str,
    stamp: str,
) -> dict[str, Any]:
    artifact_path = _selected_symbols_artifact_path(artifact_prefix, stamp)
    if not artifact_path.exists():
        return {
            "artifact_path": str(artifact_path),
            "exists": False,
            "selected_symbols": [],
            "selection_method": "default_wrapper_symbols",
            "scanner_top_n": None,
            "scanner_output_path": None,
            "source": None,
            "timestamp": None,
        }
    payload = _load_json(artifact_path.read_text(encoding="utf-8"))
    payload["artifact_path"] = str(artifact_path)
    payload["exists"] = True
    if not isinstance(payload.get("selected_symbols"), list):
        payload["selected_symbols"] = []
    return payload


def discover_execution_cost_diagnostic_context(
    artifact_prefix: str,
    stamp: str,
) -> dict[str, Any]:
    json_path = _execution_cost_diagnostic_json_path(artifact_prefix, stamp)
    md_path = _execution_cost_diagnostic_md_path(artifact_prefix, stamp)
    return {
        "json_path": str(json_path),
        "md_path": str(md_path),
        "json_exists": json_path.exists(),
        "md_exists": md_path.exists(),
    }


def build_formula_provenance_payload() -> dict[str, Any]:
    return {
        "generated_at": selection_timestamp(),
        "runtime_behavior_neutral": True,
        "formula_checks": {
            "mean_edge_over_fee = mean_gross_fill_model - mean_fee_total": True,
            (
                "shadow_execution_cost_total = mean_fee_total + "
                "mean_spread_slippage_proxy"
            ): True,
            (
                "shadow_edge_after_execution_cost = mean_gross_fill_model - "
                "shadow_execution_cost_total"
            ): True,
        },
        "fields": [
            {
                "field": "mean_gross_fill_model",
                "source_module": "Alpha_Zol0-lvl_5-main/core/BotCore.py",
                "source_function": "_update_symbol_strategy_side_edge_perf",
                "input_fields": [
                    "pnl_decompose.gross_fill_pnl_model",
                    "symbol_strategy_side_edge_perf[symbol][strategy][side]['gross']",
                ],
                "output_field": "entry_edge_over_fee.mean_gross_fill_model",
                "runtime_payload_path": (
                    "decision.details.entry_edge_over_fee.mean_gross_fill_model"
                ),
                "downstream_consumers": [
                    "entry_expected_edge_after_fee",
                    "shadow_edge_after_execution_cost",
                    "entry_edge_after_execution.edge_after_execution",
                ],
            },
            {
                "field": "mean_fee_total",
                "source_module": "Alpha_Zol0-lvl_5-main/core/BotCore.py",
                "source_function": "_update_symbol_strategy_side_edge_perf",
                "input_fields": [
                    "pnl_decompose.fee_total",
                    "symbol_strategy_side_edge_perf[symbol][strategy][side]['fee']",
                ],
                "output_field": "entry_edge_over_fee.mean_fee_total",
                "runtime_payload_path": (
                    "decision.details.entry_edge_over_fee.mean_fee_total"
                ),
                "downstream_consumers": [
                    "mean_edge_over_fee",
                    "shadow_execution_cost_total",
                    "entry_edge_after_execution.cost_model_error_vs_fee_only",
                ],
            },
            {
                "field": "mean_spread_slippage_proxy",
                "source_module": "Alpha_Zol0-lvl_5-main/core/BotCore.py",
                "source_function": (
                    "_record_strategy_and_ai_feedback -> "
                    "_update_symbol_strategy_side_edge_perf"
                ),
                "input_fields": [
                    "pnl_decompose.spread_cost",
                    "pnl_decompose.slippage_cost",
                    "spread_slippage_proxy = spread_cost + slippage_cost",
                ],
                "output_field": "entry_edge_over_fee.mean_spread_slippage_proxy",
                "runtime_payload_path": (
                    "decision.details.entry_edge_over_fee.mean_spread_slippage_proxy"
                ),
                "downstream_consumers": [
                    "shadow_execution_cost_total",
                    "shadow_edge_after_execution_cost",
                ],
            },
            {
                "field": "mean_edge_over_fee",
                "source_module": "Alpha_Zol0-lvl_5-main/core/BotCore.py",
                "source_function": "_entry_edge_over_fee_check",
                "input_fields": ["mean_gross_fill_model", "mean_fee_total"],
                "output_field": "entry_edge_over_fee.mean_edge_over_fee",
                "runtime_payload_path": (
                    "decision.details.entry_edge_over_fee.mean_edge_over_fee"
                ),
                "downstream_consumers": [
                    "entry_expected_edge_after_fee",
                    "entry_proxy_candidate.expected_edge_after_fee",
                    "entry_edge_eval.expected_edge_after_fee",
                ],
            },
            {
                "field": "shadow_execution_cost_total",
                "source_module": "Alpha_Zol0-lvl_5-main/core/BotCore.py",
                "source_function": "_entry_edge_over_fee_check",
                "input_fields": ["mean_fee_total", "mean_spread_slippage_proxy"],
                "output_field": "entry_edge_over_fee.shadow_execution_cost_total",
                "runtime_payload_path": (
                    "decision.details.entry_edge_over_fee.shadow_execution_cost_total"
                ),
                "downstream_consumers": [
                    "shadow_edge_after_execution_cost",
                    "entry_edge_after_execution.cost_model_error_vs_shadow",
                ],
            },
            {
                "field": "shadow_edge_after_execution_cost",
                "source_module": "Alpha_Zol0-lvl_5-main/core/BotCore.py",
                "source_function": "_entry_edge_over_fee_check",
                "input_fields": [
                    "mean_gross_fill_model",
                    "shadow_execution_cost_total",
                ],
                "output_field": (
                    "entry_edge_over_fee.shadow_edge_after_execution_cost"
                ),
                "runtime_payload_path": (
                    "decision.details.entry_edge_over_fee."
                    "shadow_edge_after_execution_cost"
                ),
                "downstream_consumers": [
                    "shadow_blocked_counterfactual",
                    "shadow promotion validation audit",
                ],
            },
            {
                "field": "entry_live_edge.live_edge_proxy",
                "source_module": "Alpha_Zol0-lvl_5-main/core/BotCore.py",
                "source_function": "decision loop live-edge evaluation",
                "input_fields": ["abs(signal_score)", "volatility"],
                "output_field": "entry_live_edge.live_edge_proxy",
                "runtime_payload_path": (
                    "decision.details.entry_live_edge.live_edge_proxy"
                ),
                "downstream_consumers": ["entry_live_edge.pass", "entry_reason"],
            },
            {
                "field": "entry_proxy_candidate.expected_edge_after_fee",
                "source_module": "Alpha_Zol0-lvl_5-main/core/BotCore.py",
                "source_function": "decision loop candidate proxy assembly",
                "input_fields": ["entry_expected_edge_after_fee", "router_lead"],
                "output_field": "entry_proxy_candidate.expected_edge_after_fee",
                "runtime_payload_path": (
                    "decision.details.entry_proxy_candidate.expected_edge_after_fee"
                ),
                "downstream_consumers": [
                    "entry_proxy_candidate.candidate_proxy_value",
                    "proxy validation audits",
                ],
            },
        ],
    }


def write_formula_provenance_artifacts() -> dict[str, str]:
    payload = build_formula_provenance_payload()
    FORMULA_PROVENANCE_JSON.parent.mkdir(parents=True, exist_ok=True)
    FORMULA_PROVENANCE_MD.parent.mkdir(parents=True, exist_ok=True)
    FORMULA_PROVENANCE_JSON.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    lines = [
        "EXECUTION_COST_FORMULA_PROVENANCE",
        "",
        "FORMULA_CHECKS",
    ]
    for name, value in payload["formula_checks"].items():
        lines.append(f"{name}: {value}")
    lines.append("")
    lines.append("FIELDS")
    for item in payload["fields"]:
        lines.append(f"field: {item['field']}")
        lines.append(f"source_module: {item['source_module']}")
        lines.append(f"source_function: {item['source_function']}")
        lines.append(f"runtime_payload_path: {item['runtime_payload_path']}")
        lines.append("")
    FORMULA_PROVENANCE_MD.write_text("\n".join(lines), encoding="utf-8")
    return {
        "json_path": str(FORMULA_PROVENANCE_JSON),
        "md_path": str(FORMULA_PROVENANCE_MD),
    }


def discover_fresh_artifacts(
    artifact_prefix: str,
    stamp: str,
    expected_seeds: set[int] | None = None,
) -> tuple[list[FreshArtifacts], dict[str, Any]]:
    pattern = f"{artifact_prefix}_seed*_{stamp}_paper_v2.db"
    db_paths = sorted(AUTOPSY.glob(pattern))
    artifacts: list[FreshArtifacts] = []
    discovered_seeds: set[int] = set()
    for db_path in db_paths:
        seed = _extract_seed_from_path(db_path)
        if seed is None:
            continue
        discovered_seeds.add(int(seed))
        base = db_path.name[: -len("_paper_v2.db")]
        artifacts.append(
            FreshArtifacts(
                seed=int(seed),
                db_path=db_path,
                result_json=AUTOPSY / f"{base}_paper_v2_results.json",
                fee_json=AUTOPSY / f"{base.replace('_paper_v2', '')}_fee_sanity.json",
                calibration_json=AUTOPSY
                / (
                    f"{base.replace('_paper_v2', '')}"
                    "_entry_live_edge_calibration.json"
                ),
                stdout_log=AUTOPSY / f"{base.replace('_paper_v2', '')}.out.log",
                stderr_log=AUTOPSY / f"{base.replace('_paper_v2', '')}.err.log",
                wrapper_log=AUTOPSY / f"{base.replace('_paper_v2', '')}.wrapper.log",
            )
        )
    expected = set(expected_seeds or discovered_seeds)
    metadata = {
        "pattern": pattern,
        "discovered_db_count": len(artifacts),
        "expected_seed_count": len(expected),
        "discovered_seeds": sorted(discovered_seeds),
        "expected_seeds": sorted(expected),
        "unexpected_seeds": sorted(discovered_seeds - expected),
        "missing_seeds": sorted(expected - discovered_seeds),
    }
    return artifacts, metadata


def validate_runtime_source() -> dict[str, Any]:
    stage = StageRecorder("module_io_runtime_semantics")
    text = _load_text(BOTCORE_PATH)
    required_fragments = {
        "edge_gate_formula": [
            "edge_over_fee = float(mean_gross) - float(mean_fee)",
            "shadow_execution_cost_total = (",
            "float(mean_fee) + float(mean_spread_slippage_proxy)",
            "shadow_edge_after_execution_cost = (",
            "float(mean_gross) - float(shadow_execution_cost_total)",
        ],
        "gate_routing": [
            '"mean_spread_slippage_proxy": mean_spread_slippage_proxy',
            '"shadow_execution_cost_total": shadow_execution_cost_total',
            '"shadow_edge_after_execution_cost": (',
            '"shadow_blocked_counterfactual": shadow_blocked_counterfactual',
            '"bucket_used_final": bucket_used_final',
        ],
        "decision_payload_logging": [
            '"entry_edge_over_fee": entry_edge_over_fee_status',
            '"computed_edge_over_fee": edge_over_fee_value',
            '"spread_slippage_proxy_metric": (',
            '"shadow_execution_cost_total": (',
            '"shadow_blocked_counterfactual": (',
        ],
        "close_feedback_update": [
            "spread_cost_proxy = _safe_float(pnl_decompose.get(\"spread_cost\"))",
            "slippage_cost_proxy = _safe_float(pnl_decompose.get(\"slippage_cost\"))",
            "_update_symbol_strategy_side_edge_perf(",
            "spread_slippage_proxy,",
        ],
    }
    for name, fragments in required_fragments.items():
        missing = [fragment for fragment in fragments if fragment not in text]
        stage.check(
            f"{name} fragments preserved in BotCore",
            not missing,
            {"missing": missing},
        )
    return stage.finalize()


def validate_artifacts(
    artifacts: list[FreshArtifacts],
    discovery_meta: dict[str, Any],
) -> dict[str, Any]:
    stage = StageRecorder("db_discovery_and_artifact_prefix_filtering")
    _recover_missing_artifact_sidecars(artifacts)
    stage.check(
        "fresh DB count meets minimum",
        len(artifacts) >= MIN_FRESH_DB_COUNT,
        {"discovered": len(artifacts), "minimum": MIN_FRESH_DB_COUNT},
    )
    stage.check(
        "no missing seeds in current pass",
        not discovery_meta.get("missing_seeds"),
        discovery_meta,
    )
    stage.check(
        "no unexpected seeds in current pass",
        not discovery_meta.get("unexpected_seeds"),
        discovery_meta,
    )
    for artifact in artifacts:
        for path_name, path_value in {
            "db_path": artifact.db_path,
            "result_json": artifact.result_json,
            "fee_json": artifact.fee_json,
            "calibration_json": artifact.calibration_json,
            "stdout_log": artifact.stdout_log,
            "stderr_log": artifact.stderr_log,
            "wrapper_log": artifact.wrapper_log,
        }.items():
            stage.check(
                f"artifact exists for seed {artifact.seed}: {path_name}",
                path_value.exists(),
                {"path": str(path_value)},
            )
        if artifact.result_json.exists():
            payload = _load_json(artifact.result_json.read_text(encoding="utf-8"))
            summary_db_path = payload.get("db_path")
            stage.check(
                f"runner summary db_path matches fresh DB for seed {artifact.seed}",
                _normalize_db_path_for_compare(summary_db_path)
                == _normalize_db_path_for_compare(artifact.db_path),
                {
                    "reported_db_path": summary_db_path,
                    "expected_db_path": str(artifact.db_path),
                    "reported_db_path_normalized": _normalize_db_path_for_compare(
                        summary_db_path
                    ),
                    "expected_db_path_normalized": _normalize_db_path_for_compare(
                        artifact.db_path
                    ),
                },
            )
        if artifact.db_path.exists():
            run_metrics = _extract_run_metrics(artifact.db_path)
            stage.check(
                f"run metrics extracted for seed {artifact.seed}",
                isinstance(run_metrics, dict) and bool(run_metrics),
                {
                    "close_count": run_metrics.get("close_count"),
                    "open_count": run_metrics.get("open_count"),
                },
            )
    return stage.finalize()


def load_decision_rows(
    artifacts: list[FreshArtifacts],
) -> tuple[list[DecisionRow], dict[str, Any], dict[str, Any], dict[str, Any]]:
    stage = StageRecorder("decision_payload_and_field_extraction")
    rows: list[DecisionRow] = []
    payload_stats: dict[str, Any] = {
        "decision_rows_total": 0,
        "payload_rows_with_candidate": 0,
        "payload_rows_with_edge_guard": 0,
        "payload_rows_with_realtime_snapshot": 0,
        "payload_rows_with_edge_after_execution": 0,
        "audited_rows": 0,
        "history_ready_rows": 0,
        "history_ready_rows_with_realtime_snapshot": 0,
        "admitted_rows": 0,
        "admitted_near_threshold_rows": 0,
    }
    formula_stats = {
        "current_formula_mismatches": 0,
        "shadow_cost_formula_mismatches": 0,
        "shadow_edge_formula_mismatches": 0,
        "blocked_formula_mismatches": 0,
        "shadow_blocked_formula_mismatches": 0,
        "history_ready_mismatches": 0,
        "realtime_cost_formula_mismatches": 0,
        "realtime_edge_formula_mismatches": 0,
        "realtime_error_vs_shadow_mismatches": 0,
        "realtime_error_vs_fee_only_mismatches": 0,
        "realtime_snapshot_missing_required_fields": 0,
        "realtime_snapshot_invalid_source_quality": 0,
        "realtime_snapshot_negative_spread_pct": 0,
        "realtime_snapshot_negative_fee_total": 0,
        "realtime_snapshot_negative_slippage_total": 0,
        "realtime_snapshot_negative_execution_cost": 0,
        "bucket_source_invalid": 0,
        "negative_fee_rows": 0,
        "negative_shadow_proxy_rows": 0,
        "negative_threshold_rows": 0,
    }
    per_db_counts: dict[str, dict[str, int]] = {}
    for artifact in artifacts:
        conn = sqlite3.connect(str(artifact.db_path))
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            db_rows = cur.execute(
                "select rowid as decision_rowid, timestamp, details "
                "from decisions order by rowid"
            ).fetchall()
        finally:
            conn.close()
        per_db_counts[str(artifact.db_path)] = {"decision_rows": len(db_rows)}
        payload_stats["decision_rows_total"] += len(db_rows)
        for db_row in db_rows:
            payload = _load_json(db_row["details"])
            candidate = payload.get("entry_proxy_candidate")
            edge = payload.get("entry_edge_over_fee")
            realtime_snapshot = payload.get("execution_snapshot")
            if not isinstance(realtime_snapshot, dict):
                realtime_snapshot = payload.get("entry_execution_snapshot_realtime")
            realtime_edge_diagnostic = payload.get("entry_edge_after_execution")
            live_edge_status = payload.get("entry_live_edge")
            if isinstance(candidate, dict):
                payload_stats["payload_rows_with_candidate"] += 1
            if isinstance(edge, dict):
                payload_stats["payload_rows_with_edge_guard"] += 1
            if isinstance(realtime_snapshot, dict):
                payload_stats["payload_rows_with_realtime_snapshot"] += 1
            if isinstance(realtime_edge_diagnostic, dict):
                payload_stats["payload_rows_with_edge_after_execution"] += 1
            if not isinstance(candidate, dict) or not isinstance(edge, dict):
                continue
            timestamp = _parse_db_timestamp(db_row["timestamp"])
            if timestamp is None:
                stage.warn(
                    "Skipping decision row with unparsable timestamp in "
                    f"{artifact.db_path.name}"
                )
                continue
            raw_decision = (
                str(payload.get("entry_decision_raw") or "").strip().lower() or None
            )
            final_decision = (
                str(payload.get("entry_decision_final") or "").strip().lower()
                or None
            )
            current_edge = _safe_float(edge.get("mean_edge_over_fee"))
            current_gross = _safe_float(edge.get("mean_gross_fill_model"))
            current_fee = _safe_float(edge.get("mean_fee_total"))
            threshold = _safe_float(edge.get("min_edge_over_fee"))
            shadow_proxy = _safe_float(edge.get("mean_spread_slippage_proxy"))
            shadow_cost = _safe_float(edge.get("shadow_execution_cost_total"))
            shadow_edge = _safe_float(edge.get("shadow_edge_after_execution_cost"))
            candidate_history_ready = bool(candidate.get("history_ready"))
            edge_history_ready = bool(edge.get("history_ready"))
            bucket_source = str(edge.get("bucket_used_final") or "") or None
            trade_count = int(edge.get("trade_count") or 0)
            trade_count_primary = int(edge.get("trade_count_primary") or 0)
            trade_count_fallback = int(edge.get("trade_count_fallback") or 0)
            current_margin = None
            shadow_margin = None
            if current_edge is not None and threshold is not None:
                current_margin = float(current_edge) - float(threshold)
            if shadow_edge is not None and threshold is not None:
                shadow_margin = float(shadow_edge) - float(threshold)
            current_margin_bucket = _margin_bucket(current_margin)
            shadow_margin_bucket = _margin_bucket(shadow_margin)
            current_formula = None
            shadow_cost_formula = None
            shadow_edge_formula = None
            blocked_formula = None
            shadow_blocked_formula = None
            if current_gross is not None and current_fee is not None:
                current_formula = float(current_gross) - float(current_fee)
            if current_fee is not None and shadow_proxy is not None:
                shadow_cost_formula = float(current_fee) + float(shadow_proxy)
            if current_gross is not None and shadow_cost_formula is not None:
                shadow_edge_formula = float(current_gross) - float(shadow_cost_formula)
            realtime_fee_total = _snapshot_float(
                realtime_snapshot,
                "expected_fee_total",
            )
            realtime_slippage_total = _snapshot_float(
                realtime_snapshot,
                "slippage_proxy_total",
            )
            realtime_cost_total = _snapshot_float(
                realtime_snapshot,
                "execution_cost_total_realtime",
            )
            realtime_edge_after_cost = _snapshot_float(
                realtime_snapshot,
                "edge_after_realtime_cost",
            )
            realtime_error_vs_shadow = _snapshot_float(
                realtime_edge_diagnostic,
                "cost_model_error_vs_shadow",
            )
            realtime_error_vs_fee_only = _snapshot_float(
                realtime_edge_diagnostic,
                "cost_model_error_vs_fee_only",
            )
            realtime_cost_formula = None
            realtime_edge_formula = None
            if realtime_fee_total is not None or realtime_slippage_total is not None:
                realtime_cost_formula = float(realtime_fee_total or 0.0) + float(
                    realtime_slippage_total or 0.0
                )
            if current_gross is not None and realtime_cost_formula is not None:
                realtime_edge_formula = float(current_gross) - float(
                    realtime_cost_formula
                )
            if isinstance(realtime_snapshot, dict):
                missing_snapshot_fields = [
                    key
                    for key in (
                        "bid",
                        "ask",
                        "mid",
                        "spread_abs",
                        "spread_pct",
                        "maker_fee_rate",
                        "taker_fee_rate",
                        "expected_size_usdt",
                        "expected_fee_open",
                        "expected_fee_close",
                        "expected_fee_total",
                        "slippage_proxy_open",
                        "slippage_proxy_close",
                        "slippage_proxy_total",
                        "execution_cost_total_realtime",
                        "edge_after_realtime_cost",
                        "source_quality",
                    )
                    if key not in realtime_snapshot
                ]
                if missing_snapshot_fields:
                    formula_stats["realtime_snapshot_missing_required_fields"] += 1
                source_quality = str(
                    realtime_snapshot.get("source_quality") or ""
                ).strip()
                if source_quality not in {"full_depth", "top_of_book", "proxy"}:
                    formula_stats["realtime_snapshot_invalid_source_quality"] += 1
                if realtime_snapshot.get("spread_pct") is not None and float(
                    realtime_snapshot.get("spread_pct") or 0.0
                ) < 0.0:
                    formula_stats["realtime_snapshot_negative_spread_pct"] += 1
                if realtime_fee_total is not None and realtime_fee_total < 0.0:
                    formula_stats["realtime_snapshot_negative_fee_total"] += 1
                if (
                    realtime_slippage_total is not None
                    and realtime_slippage_total < 0.0
                ):
                    formula_stats["realtime_snapshot_negative_slippage_total"] += 1
                if realtime_cost_total is not None and realtime_cost_total < 0.0:
                    formula_stats["realtime_snapshot_negative_execution_cost"] += 1
            if threshold is not None and current_edge is not None:
                blocked_formula = bool(edge_history_ready and current_edge < threshold)
            if threshold is not None and shadow_edge is not None:
                shadow_blocked_formula = bool(
                    edge_history_ready and shadow_edge < threshold
                )
            if current_formula is not None and not _float_equal(
                current_edge,
                current_formula,
            ):
                formula_stats["current_formula_mismatches"] += 1
            if (
                shadow_cost_formula is not None
                and not _float_equal(shadow_cost, shadow_cost_formula)
            ):
                formula_stats["shadow_cost_formula_mismatches"] += 1
            if (
                shadow_edge_formula is not None
                and not _float_equal(shadow_edge, shadow_edge_formula)
            ):
                formula_stats["shadow_edge_formula_mismatches"] += 1
            if (
                realtime_cost_formula is not None
                and realtime_cost_total is not None
                and not _float_equal(realtime_cost_total, realtime_cost_formula)
            ):
                formula_stats["realtime_cost_formula_mismatches"] += 1
            if (
                realtime_edge_formula is not None
                and realtime_edge_after_cost is not None
                and not _float_equal(realtime_edge_after_cost, realtime_edge_formula)
            ):
                formula_stats["realtime_edge_formula_mismatches"] += 1
            if (
                realtime_cost_total is not None
                and shadow_cost is not None
                and realtime_error_vs_shadow is not None
                and not _float_equal(
                    realtime_error_vs_shadow,
                    float(realtime_cost_total) - float(shadow_cost),
                )
            ):
                formula_stats["realtime_error_vs_shadow_mismatches"] += 1
            if (
                realtime_cost_total is not None
                and current_fee is not None
                and realtime_error_vs_fee_only is not None
                and not _float_equal(
                    realtime_error_vs_fee_only,
                    float(realtime_cost_total) - float(current_fee),
                )
            ):
                formula_stats["realtime_error_vs_fee_only_mismatches"] += 1
            if (
                blocked_formula is not None
                and bool(edge.get("blocked")) != blocked_formula
            ):
                formula_stats["blocked_formula_mismatches"] += 1
            if (
                shadow_blocked_formula is not None
                and bool(edge.get("shadow_blocked_counterfactual"))
                != shadow_blocked_formula
            ):
                formula_stats["shadow_blocked_formula_mismatches"] += 1
            if candidate_history_ready != edge_history_ready:
                formula_stats["history_ready_mismatches"] += 1
            if bucket_source not in {"primary", "fallback"}:
                formula_stats["bucket_source_invalid"] += 1
            if current_fee is not None and current_fee < 0.0:
                formula_stats["negative_fee_rows"] += 1
            if shadow_proxy is not None and shadow_proxy < 0.0:
                formula_stats["negative_shadow_proxy_rows"] += 1
            if threshold is not None and threshold < 0.0:
                formula_stats["negative_threshold_rows"] += 1
            shadow_counterfactual_fields = (
                _derive_shadow_counterfactual_analysis_fields(
                    shadow_edge_after_execution_cost=shadow_edge,
                    threshold=threshold,
                    history_ready=edge_history_ready,
                    payload_raw=edge.get("shadow_counterfactual_raw"),
                    payload_history_gated=edge.get(
                        "shadow_counterfactual_history_gated"
                    ),
                    payload_exclusion_reason=edge.get(
                        "shadow_counterfactual_history_exclusion_reason"
                    ),
                    payload_forensic_class=edge.get(
                        "shadow_counterfactual_forensic_class"
                    ),
                )
            )
            row = DecisionRow(
                db_path=artifact.db_path,
                decision_rowid=int(db_row["decision_rowid"]),
                timestamp=timestamp,
                symbol=str(payload.get("symbol") or edge.get("symbol") or "") or None,
                side=_normalize_side(
                    edge.get("side") or raw_decision or final_decision
                ),
                mr_pocket_symbol=(
                    str(payload.get("mr_pocket_symbol") or "").strip() or None
                ),
                mr_pocket_side=(
                    str(payload.get("mr_pocket_side") or "").strip().lower() or None
                ),
                mr_pocket_regime=(
                    str(payload.get("mr_pocket_regime") or "").strip().lower()
                    or None
                ),
                mr_pocket_atr_bucket=(
                    str(payload.get("mr_pocket_atr_bucket") or "").strip() or None
                ),
                mr_pocket_score_bucket=(
                    str(payload.get("mr_pocket_score_bucket") or "").strip() or None
                ),
                mr_pocket_tuple=(
                    str(payload.get("mr_pocket_tuple") or "").strip() or None
                ),
                mr_gate_action=(
                    str(payload.get("mr_gate_action") or "").strip().lower()
                    or None
                ),
                mr_gate_reason=(
                    str(payload.get("mr_gate_reason") or "").strip() or None
                ),
                mr_gate_runtime_decision_unchanged=(
                    bool(payload.get("mr_gate_runtime_decision_unchanged"))
                    if payload.get("mr_gate_runtime_decision_unchanged") is not None
                    else None
                ),
                raw_decision=raw_decision,
                final_decision=final_decision,
                entry_reason=str(payload.get("entry_reason") or "").strip().lower()
                or None,
                candidate_history_ready=candidate_history_ready,
                candidate_proxy_value=_safe_float(
                    candidate.get("candidate_proxy_value")
                ),
                candidate_expected_edge_after_fee=_safe_float(
                    candidate.get("expected_edge_after_fee")
                ),
                candidate_router_lead=_safe_float(candidate.get("router_lead")),
                edge_history_ready=edge_history_ready,
                bucket_source=bucket_source,
                trade_count=trade_count,
                trade_count_primary=trade_count_primary,
                trade_count_fallback=trade_count_fallback,
                strategy=str(edge.get("strategy") or "") or None,
                current_mean_gross_fill_model=current_gross,
                current_mean_fee_total=current_fee,
                current_edge_over_fee_value=current_edge,
                active_threshold=threshold,
                current_margin_to_threshold=current_margin,
                shadow_spread_slippage_proxy=shadow_proxy,
                shadow_execution_cost_total=shadow_cost,
                shadow_edge_after_execution_cost=shadow_edge,
                shadow_margin_to_threshold=shadow_margin,
                current_gate_blocked=bool(edge.get("blocked")),
                shadow_gate_blocked=bool(edge.get("shadow_blocked_counterfactual")),
                shadow_counterfactual_raw=shadow_counterfactual_fields.get(
                    "shadow_counterfactual_raw"
                ),
                shadow_counterfactual_history_gated=(
                    shadow_counterfactual_fields.get(
                        "shadow_counterfactual_history_gated"
                    )
                ),
                shadow_counterfactual_history_exclusion_reason=(
                    shadow_counterfactual_fields.get(
                        "shadow_counterfactual_history_exclusion_reason"
                    )
                ),
                shadow_counterfactual_forensic_class=(
                    shadow_counterfactual_fields.get(
                        "shadow_counterfactual_forensic_class"
                    )
                ),
                mr_features=_extract_mr_features_from_payload(payload),
                mr_shadow_rule_pass=(
                    bool(payload.get("mr_shadow_rule_pass"))
                    if payload.get("mr_shadow_rule_pass") is not None
                    else None
                ),
                mr_shadow_rule_reject_reason=(
                    str(payload.get("mr_shadow_rule_reject_reason") or "").strip()
                    or None
                ),
                mr_shadow_rule_thresholds=(
                    payload.get("mr_shadow_rule_thresholds")
                    if isinstance(payload.get("mr_shadow_rule_thresholds"), dict)
                    else None
                ),
                mr_shadow_rule_checks=(
                    payload.get("mr_shadow_rule_checks")
                    if isinstance(payload.get("mr_shadow_rule_checks"), dict)
                    else None
                ),
                mr_shadow_rule_variant=(
                    str(payload.get("mr_shadow_rule_variant") or "").strip()
                    or None
                ),
                realtime_execution_snapshot=(
                    realtime_snapshot if isinstance(realtime_snapshot, dict) else None
                ),
                realtime_edge_diagnostic=(
                    realtime_edge_diagnostic
                    if isinstance(realtime_edge_diagnostic, dict)
                    else None
                ),
                live_edge_status=(
                    live_edge_status if isinstance(live_edge_status, dict) else None
                ),
            )
            rows.append(row)
            payload_stats["audited_rows"] += 1
            if row.edge_history_ready:
                payload_stats["history_ready_rows"] += 1
                if isinstance(row.realtime_execution_snapshot, dict):
                    payload_stats["history_ready_rows_with_realtime_snapshot"] += 1
            if row.final_decision in {"buy", "sell"}:
                payload_stats["admitted_rows"] += 1
                if _is_admitted_near_threshold_bucket(
                    current_margin_bucket,
                    shadow_margin_bucket,
                ):
                    payload_stats["admitted_near_threshold_rows"] += 1
    required_present = (
        payload_stats["payload_rows_with_candidate"]
        == payload_stats["payload_rows_with_edge_guard"]
        and payload_stats["audited_rows"] > 0
    )
    stage.check(
        "candidate and edge guard payloads are present on the same fresh rows",
        required_present,
        payload_stats,
    )
    for key, count in formula_stats.items():
        stage.check(key, count == 0, {"count": count})
    stage.check(
        "history-ready rows extracted",
        payload_stats["history_ready_rows"] > 0,
        payload_stats,
    )
    stage.check(
        "realtime execution snapshots extracted",
        payload_stats["payload_rows_with_realtime_snapshot"] > 0,
        payload_stats,
    )
    return rows, payload_stats, formula_stats, {
        "stage": stage.finalize(),
        "per_db_counts": per_db_counts,
    }


def _to_linkable_decision(row: DecisionRow) -> DecisionEval:
    return DecisionEval(
        db_path=row.db_path,
        timestamp=row.timestamp,
        symbol=row.symbol,
        raw_decision=row.raw_decision,
        final_decision=row.final_decision,
        candidate_history_ready=row.candidate_history_ready,
        candidate_value=row.candidate_proxy_value,
        candidate_expected_edge_after_fee=row.candidate_expected_edge_after_fee,
        candidate_router_lead=row.candidate_router_lead,
        old_proxy_value=None,
    )


def _to_readiness_linkage_decision(
    row: DecisionRow,
    readiness_linkage_eligible: bool,
    partial_history_ready: bool,
    excluded_reason: str | None,
) -> DecisionEval:
    return DecisionEval(
        db_path=row.db_path,
        timestamp=row.timestamp,
        symbol=row.symbol,
        raw_decision=row.raw_decision,
        final_decision=row.final_decision,
        candidate_history_ready=row.candidate_history_ready,
        candidate_value=row.candidate_proxy_value,
        candidate_expected_edge_after_fee=row.candidate_expected_edge_after_fee,
        candidate_router_lead=row.candidate_router_lead,
        old_proxy_value=None,
        readiness_linkage_eligible=readiness_linkage_eligible,
        partial_history_ready=partial_history_ready,
        linkage_excluded_reason=excluded_reason,
    )


def _is_partial_history_ready(row: DecisionRow) -> bool:
    return (not row.candidate_history_ready) and int(row.trade_count or 0) in {1, 2}


def _assess_readiness_linkage(
    row: DecisionRow,
    opens: list[Any],
    closes: dict[str, Any],
) -> dict[str, Any]:
    runtime_history_ready = bool(row.candidate_history_ready)
    partial_history_ready = _is_partial_history_ready(row)
    candidate_value_missing = row.candidate_proxy_value is None
    excluded_reason: str | None = None
    linkage_eligible = False

    if row.final_decision not in {"buy", "sell"}:
        excluded_reason = "not_admitted"
    elif row.candidate_expected_edge_after_fee is None:
        excluded_reason = "missing_expected_edge"
    elif not runtime_history_ready and not partial_history_ready:
        excluded_reason = "runtime_history_not_ready"
    else:
        match = _match_linkage_evidence(
            _to_readiness_linkage_decision(
                row,
                readiness_linkage_eligible=True,
                partial_history_ready=partial_history_ready,
                excluded_reason=None,
            ),
            opens,
            closes,
        )
        if match.get("status") == "ok":
            linkage_eligible = True
        else:
            excluded_reason = str(match.get("status") or "linkage_match_failed")

    return {
        "runtime_history_ready": runtime_history_ready,
        "partial_history_ready": partial_history_ready,
        "linkage_eligible": linkage_eligible,
        "excluded_reason": excluded_reason,
        "candidate_value_missing": candidate_value_missing,
    }


def _summarize_link_failures(
    admitted_rows: list[DecisionRow],
    opens: list[Any],
    closes: dict[str, Any],
) -> tuple[dict[str, Any], dict[tuple[str, int], dict[str, Any]]]:
    diagnostics = {
        "admitted_trade_rows": len(admitted_rows),
        "eligible_decisions": 0,
        "linkage_eligible_rows": 0,
        "linkable_decisions": 0,
        "history_not_ready_rows": 0,
        "runtime_history_not_ready_rows": 0,
        "partial_history_ready_rows": 0,
        "missing_candidate_value_rows": 0,
        "missing_expected_edge_rows": 0,
        "no_open_symbol_side_match_rows": 0,
        "missing_open_expected_edge_rows": 0,
        "no_open_expected_edge_match_rows": 0,
        "missing_open_decision_ts_rows": 0,
        "no_open_timestamp_match_rows": 0,
        "open_missing_trade_id_rows": 0,
        "open_missing_close_rows": 0,
        "excluded_reason_counts": {},
    }
    assessments: dict[tuple[str, int], dict[str, Any]] = {}
    reason_to_counter = {
        "runtime_history_not_ready": "history_not_ready_rows",
        "missing_expected_edge": "missing_expected_edge_rows",
        "no_open_symbol_side_match": "no_open_symbol_side_match_rows",
        "missing_open_expected_edge": "missing_open_expected_edge_rows",
        "no_open_expected_edge_match": "no_open_expected_edge_match_rows",
        "missing_open_decision_ts": "missing_open_decision_ts_rows",
        "no_open_timestamp_match": "no_open_timestamp_match_rows",
        "open_missing_trade_id": "open_missing_trade_id_rows",
        "open_missing_close": "open_missing_close_rows",
    }
    for row in admitted_rows:
        assessment = _assess_readiness_linkage(row, opens, closes)
        key = (str(row.db_path), row.decision_rowid)
        assessments[key] = assessment
        if not assessment["runtime_history_ready"]:
            diagnostics["history_not_ready_rows"] += 1
            diagnostics["runtime_history_not_ready_rows"] += 1
        if assessment["partial_history_ready"]:
            diagnostics["partial_history_ready_rows"] += 1
        if assessment["candidate_value_missing"]:
            diagnostics["missing_candidate_value_rows"] += 1
        if not assessment["linkage_eligible"]:
            reason = str(assessment["excluded_reason"] or "unknown")
            reason_counts = diagnostics["excluded_reason_counts"]
            reason_counts[reason] = int(reason_counts.get(reason) or 0) + 1
            counter_name = reason_to_counter.get(reason)
            if counter_name is not None:
                diagnostics[counter_name] += 1
            continue

        diagnostics["eligible_decisions"] += 1
        diagnostics["linkage_eligible_rows"] += 1
        diagnostics["linkable_decisions"] += 1

    diagnostics["unlinked_eligible_decisions"] = 0
    return diagnostics, assessments


def validate_linked_outcomes(
    artifacts: list[FreshArtifacts],
    rows: list[DecisionRow],
) -> tuple[
    dict[tuple[str, int], dict[str, Any]],
    dict[tuple[str, int], dict[str, Any]],
    dict[str, Any],
    dict[str, Any],
]:
    stage = StageRecorder("linked_open_close_reconstruction")
    linked_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    linkage_meta_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    link_stats = {
        "open_rows": 0,
        "close_rows": 0,
        "linked_rows": 0,
        "duplicate_trade_id_rows": 0,
        "cross_run_contamination_rows": 0,
        "admitted_trade_rows": 0,
        "eligible_decisions": 0,
        "linkage_eligible_rows": 0,
        "linkable_decisions": 0,
        "history_not_ready_rows": 0,
        "runtime_history_not_ready_rows": 0,
        "partial_history_ready_rows": 0,
        "missing_candidate_value_rows": 0,
        "missing_expected_edge_rows": 0,
        "no_open_symbol_side_match_rows": 0,
        "missing_open_expected_edge_rows": 0,
        "no_open_expected_edge_match_rows": 0,
        "missing_open_decision_ts_rows": 0,
        "no_open_timestamp_match_rows": 0,
        "open_missing_trade_id_rows": 0,
        "open_missing_close_rows": 0,
        "unlinked_eligible_decisions": 0,
        "excluded_reason_counts": {},
        "per_db_diagnostics": [],
    }
    for artifact in artifacts:
        opens = _load_position_opens(artifact.db_path)
        closes = _load_position_closes(artifact.db_path)
        link_stats["open_rows"] += len(opens)
        link_stats["close_rows"] += len(closes)
        admitted_rows = [
            row
            for row in rows
            if row.db_path == artifact.db_path and row.final_decision in {"buy", "sell"}
        ]
        diagnostics, assessments = _summarize_link_failures(
            admitted_rows,
            opens,
            closes,
        )
        for key, value in diagnostics.items():
            if key == "excluded_reason_counts":
                for reason, count in value.items():
                    link_stats["excluded_reason_counts"][reason] = int(
                        link_stats["excluded_reason_counts"].get(reason) or 0
                    ) + int(count)
            else:
                link_stats[key] += int(value)
        linkage_meta_by_key.update(assessments)
        linked = _link_outcomes(
            [
                _to_readiness_linkage_decision(
                    row,
                    readiness_linkage_eligible=bool(
                        assessments[(str(row.db_path), row.decision_rowid)].get(
                            "linkage_eligible"
                        )
                    ),
                    partial_history_ready=bool(
                        assessments[(str(row.db_path), row.decision_rowid)].get(
                            "partial_history_ready"
                        )
                    ),
                    excluded_reason=assessments[
                        (str(row.db_path), row.decision_rowid)
                    ].get("excluded_reason"),
                )
                for row in admitted_rows
            ],
            opens,
            closes,
        )
        seen_trade_ids: set[str] = set()
        linked_rows_for_db = 0
        for item in linked:
            trade_id = str(item.get("trade_id") or "")
            if trade_id in seen_trade_ids:
                link_stats["duplicate_trade_id_rows"] += 1
            seen_trade_ids.add(trade_id)
            if str(item.get("db_path") or "") != str(artifact.db_path):
                link_stats["cross_run_contamination_rows"] += 1
                continue
            decision_timestamp = str(item.get("decision_timestamp") or "")
            ts = _parse_db_timestamp(decision_timestamp.replace("T", " "))
            if ts is None:
                try:
                    ts = datetime.fromisoformat(decision_timestamp)
                except Exception:
                    ts = None
            if ts is None:
                continue
            matching = [
                row
                for row in admitted_rows
                if row.symbol == item.get("symbol") and row.timestamp == ts
            ]
            if not matching:
                continue
            best = matching[0]
            linked_by_key[(str(best.db_path), best.decision_rowid)] = item
            linked_rows_for_db += 1
        diagnostics["linked_rows"] = linked_rows_for_db
        diagnostics["unlinked_eligible_decisions"] = max(
            int(diagnostics.get("linkage_eligible_rows") or 0) - linked_rows_for_db,
            0,
        )
        link_stats["per_db_diagnostics"].append(
            {
                "db_path": str(artifact.db_path),
                "seed": artifact.seed,
                **diagnostics,
            }
        )
    link_stats["linked_rows"] = len(linked_by_key)
    link_stats["unlinked_eligible_decisions"] = max(
        int(link_stats.get("linkage_eligible_rows") or 0) - link_stats["linked_rows"],
        0,
    )
    stage.check(
        "linked rows do not reuse duplicate trade IDs per DB",
        link_stats["duplicate_trade_id_rows"] == 0,
        link_stats,
    )
    stage.check(
        "linked rows stay within the fresh validation pass",
        link_stats["cross_run_contamination_rows"] == 0,
        link_stats,
    )
    if link_stats["eligible_decisions"] > 0:
        stage.check(
            "eligible admitted rows retain a decision-to-open join path",
            link_stats["linkable_decisions"] > 0,
            link_stats,
        )
        stage.check(
            "linked close support exists",
            link_stats["linked_rows"] > 0,
            link_stats,
        )
    elif link_stats["admitted_trade_rows"] > 0:
        stage.warn(
            "No readiness linkage input was eligible; treat this as promotion "
            "sample insufficiency rather than a structural integrity failure."
        )
    return linked_by_key, linkage_meta_by_key, link_stats, stage.finalize()


def _group_rows(rows: list[dict[str, Any]], key_name: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = str(row.get(key_name) or "unknown")
        grouped.setdefault(key, []).append(row)
    summary: list[dict[str, Any]] = []
    for key in sorted(grouped, key=lambda item: (-len(grouped[item]), item)):
        items = grouped[key]
        summary.append(
            {
                "name": key,
                "rows": len(items),
                "current_blocked_count": sum(
                    1 for item in items if bool(item.get("current_gate_blocked"))
                ),
                "shadow_blocked_count": sum(
                    1 for item in items if bool(item.get("shadow_gate_blocked"))
                ),
                "linked_close_count": sum(
                    1 for item in items if item.get("linked_close") is not None
                ),
                "mean_current_margin": _round_float(
                    _mean([item.get("current_margin_to_threshold") for item in items])
                ),
                "mean_shadow_margin": _round_float(
                    _mean([item.get("shadow_margin_to_threshold") for item in items])
                ),
            }
        )
    return summary


def build_realtime_comparison(row_level_audit: list[dict[str, Any]]) -> dict[str, Any]:
    def _normalized_realtime_cost(row: dict[str, Any]) -> float | None:
        snapshot = row.get("execution_snapshot_realtime")
        if not isinstance(snapshot, dict):
            return None
        direct = _snapshot_float(snapshot, "execution_cost_total_realtime")
        if direct is not None:
            return direct
        fee_total = _snapshot_float(snapshot, "expected_fee_total")
        slippage_total = _snapshot_float(snapshot, "slippage_proxy_total")
        if fee_total is not None or slippage_total is not None:
            return float(fee_total or 0.0) + float(slippage_total or 0.0)
        taker_fee_rate = _snapshot_float(snapshot, "taker_fee_rate")
        spread_pct = _snapshot_float(snapshot, "spread_pct")
        if taker_fee_rate is None and spread_pct is None:
            return None
        return float((taker_fee_rate or 0.0) * 2.0) + float(spread_pct or 0.0)

    def _normalized_realtime_edge(row: dict[str, Any]) -> float | None:
        direct = _snapshot_float(
            row.get("execution_snapshot_realtime"),
            "edge_after_realtime_cost",
        )
        if direct is not None:
            return direct
        current_gross = _safe_float(row.get("current_mean_gross_fill_model"))
        realtime_cost = _normalized_realtime_cost(row)
        if current_gross is None or realtime_cost is None:
            return None
        return float(current_gross) - float(realtime_cost)

    scoped_rows = [
        row
        for row in row_level_audit
        if row.get("history_ready")
        and isinstance(row.get("execution_snapshot_realtime"), dict)
    ]
    current_costs = [
        _safe_float(row.get("current_mean_fee_total")) for row in scoped_rows
    ]
    shadow_costs = [
        _safe_float(row.get("shadow_execution_cost_total")) for row in scoped_rows
    ]
    realtime_costs = [
        _normalized_realtime_cost(row)
        for row in scoped_rows
    ]
    current_edges = [
        _safe_float(row.get("current_edge_over_fee_value")) for row in scoped_rows
    ]
    shadow_edges = [
        _safe_float(row.get("shadow_edge_after_execution_cost")) for row in scoped_rows
    ]
    realtime_edges = [
        _normalized_realtime_edge(row)
        for row in scoped_rows
    ]
    comparable_rows = 0
    current_optimistic_count = 0
    shadow_optimistic_count = 0
    shadow_closer_count = 0
    current_closer_count = 0
    equal_distance_count = 0
    errors_vs_shadow: list[float | None] = []
    errors_vs_fee_only: list[float | None] = []
    for row in scoped_rows:
        current_cost = _safe_float(row.get("current_mean_fee_total"))
        shadow_cost = _safe_float(row.get("shadow_execution_cost_total"))
        realtime_cost = _normalized_realtime_cost(row)
        edge_diag = row.get("entry_edge_after_execution") or {}
        errors_vs_shadow.append(
            _safe_float(edge_diag.get("cost_model_error_vs_shadow"))
        )
        errors_vs_fee_only.append(
            _safe_float(edge_diag.get("cost_model_error_vs_fee_only"))
        )
        if (
            current_cost is None
            or shadow_cost is None
            or realtime_cost is None
        ):
            continue
        comparable_rows += 1
        if float(current_cost) + FLOAT_TOLERANCE < float(realtime_cost):
            current_optimistic_count += 1
        if float(shadow_cost) + FLOAT_TOLERANCE < float(realtime_cost):
            shadow_optimistic_count += 1
        current_distance = abs(float(current_cost) - float(realtime_cost))
        shadow_distance = abs(float(shadow_cost) - float(realtime_cost))
        if shadow_distance + FLOAT_TOLERANCE < current_distance:
            shadow_closer_count += 1
        elif current_distance + FLOAT_TOLERANCE < shadow_distance:
            current_closer_count += 1
        else:
            equal_distance_count += 1
    return {
        "rows_with_history_and_realtime_snapshot": len(scoped_rows),
        "rows_cost_comparable": comparable_rows,
        "mean_current_fee_only_cost": _round_float(_mean(current_costs)),
        "mean_shadow_cost": _round_float(_mean(shadow_costs)),
        "mean_realtime_cost": _round_float(_mean(realtime_costs)),
        "mean_current_edge": _round_float(_mean(current_edges)),
        "mean_shadow_edge": _round_float(_mean(shadow_edges)),
        "mean_realtime_edge": _round_float(_mean(realtime_edges)),
        "current_fee_only_optimistic_vs_realtime_count": current_optimistic_count,
        "shadow_cost_optimistic_vs_realtime_count": shadow_optimistic_count,
        "shadow_closer_to_realtime_count": shadow_closer_count,
        "current_closer_to_realtime_count": current_closer_count,
        "equal_distance_count": equal_distance_count,
        "current_fee_only_optimistic_vs_realtime_share": _round_float(
            (float(current_optimistic_count) / float(comparable_rows))
            if comparable_rows > 0
            else None
        ),
        "shadow_cost_optimistic_vs_realtime_share": _round_float(
            (float(shadow_optimistic_count) / float(comparable_rows))
            if comparable_rows > 0
            else None
        ),
        "shadow_closer_to_realtime_share": _round_float(
            (float(shadow_closer_count) / float(comparable_rows))
            if comparable_rows > 0
            else None
        ),
        "mean_cost_model_error_vs_shadow": _round_float(_mean(errors_vs_shadow)),
        "mean_cost_model_error_vs_fee_only": _round_float(
            _mean(errors_vs_fee_only)
        ),
    }


def assemble_shadow_audit(
    rows: list[DecisionRow],
    linked_by_key: dict[tuple[str, int], dict[str, Any]],
    linkage_meta_by_key: dict[tuple[str, int], dict[str, Any]],
    link_stats: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    stage = StageRecorder("summary_aggregation_and_classifier_input_assembly")
    row_level_audit: list[dict[str, Any]] = []
    for row in rows:
        linked = linked_by_key.get((str(row.db_path), row.decision_rowid))
        linkage_meta = linkage_meta_by_key.get(
            (str(row.db_path), row.decision_rowid),
            {},
        )
        linked_close = None
        linked_positive = None
        if linked is not None:
            net_pnl = _safe_float(linked.get("net_pnl"))
            linked_positive = bool(net_pnl is not None and net_pnl > 0.0)
            linked_close = {
                "trade_id": linked.get("trade_id"),
                "net_pnl": _round_float(net_pnl),
                "gross_pnl": _round_float(_safe_float(linked.get("gross_pnl"))),
                "feasible_net": _round_float(
                    _safe_float(linked.get("feasible_net"))
                ),
                "hard_close": bool(linked.get("hard_close")),
                "close_reason": linked.get("close_reason"),
            }
        row_level_audit.append(
            {
                "db_path": str(row.db_path),
                "seed": _extract_seed_from_path(row.db_path),
                "decision_rowid": row.decision_rowid,
                "timestamp": row.timestamp.isoformat(),
                "stable_row_key": (
                    f"{row.db_path.name}:{row.decision_rowid}:"
                    f"{row.timestamp.isoformat()}"
                ),
                "symbol": row.symbol,
                "side": row.side,
                "mr_pocket_symbol": row.mr_pocket_symbol,
                "mr_pocket_side": row.mr_pocket_side,
                "mr_pocket_regime": row.mr_pocket_regime,
                "mr_pocket_atr_bucket": row.mr_pocket_atr_bucket,
                "mr_pocket_score_bucket": row.mr_pocket_score_bucket,
                "mr_pocket_tuple": row.mr_pocket_tuple,
                "mr_gate_action": row.mr_gate_action,
                "mr_gate_reason": row.mr_gate_reason,
                "mr_gate_runtime_decision_unchanged": (
                    row.mr_gate_runtime_decision_unchanged
                ),
                "bucket_source": row.bucket_source,
                "trade_count": row.trade_count,
                "trade_count_primary": row.trade_count_primary,
                "trade_count_fallback": row.trade_count_fallback,
                "strategy": row.strategy,
                "raw_decision": row.raw_decision,
                "final_decision": row.final_decision,
                "entry_reason": row.entry_reason,
                "history_ready": row.edge_history_ready,
                "runtime_history_ready": bool(
                    linkage_meta.get(
                        "runtime_history_ready",
                        row.candidate_history_ready,
                    )
                ),
                "candidate_history_ready": row.candidate_history_ready,
                "partial_history_ready": bool(
                    linkage_meta.get("partial_history_ready")
                ),
                "linkage_eligible": bool(linkage_meta.get("linkage_eligible")),
                "excluded_reason": linkage_meta.get("excluded_reason"),
                "current_gate_blocked": row.current_gate_blocked,
                "current_mean_gross_fill_model": _round_float(
                    row.current_mean_gross_fill_model
                ),
                "current_mean_fee_total": _round_float(row.current_mean_fee_total),
                "current_edge_over_fee_value": _round_float(
                    row.current_edge_over_fee_value
                ),
                "active_threshold": _round_float(row.active_threshold),
                "current_margin_to_threshold": _round_float(
                    row.current_margin_to_threshold
                ),
                "current_margin_bucket": _margin_bucket(
                    row.current_margin_to_threshold
                ),
                "shadow_spread_slippage_proxy": _round_float(
                    row.shadow_spread_slippage_proxy
                ),
                "shadow_execution_cost_total": _round_float(
                    row.shadow_execution_cost_total
                ),
                "shadow_edge_after_execution_cost": _round_float(
                    row.shadow_edge_after_execution_cost
                ),
                "shadow_margin_to_threshold": _round_float(
                    row.shadow_margin_to_threshold
                ),
                "shadow_margin_bucket": _margin_bucket(
                    row.shadow_margin_to_threshold
                ),
                "shadow_gate_blocked": row.shadow_gate_blocked,
                "shadow_counterfactual_raw": row.shadow_counterfactual_raw,
                "shadow_counterfactual_history_gated": (
                    row.shadow_counterfactual_history_gated
                ),
                "shadow_counterfactual_history_exclusion_reason": (
                    row.shadow_counterfactual_history_exclusion_reason
                ),
                "shadow_counterfactual_forensic_class": (
                    row.shadow_counterfactual_forensic_class
                ),
                "mr_features": row.mr_features,
                "mr_shadow_rule_pass": row.mr_shadow_rule_pass,
                "mr_shadow_rule_reject_reason": row.mr_shadow_rule_reject_reason,
                "mr_shadow_rule_thresholds": row.mr_shadow_rule_thresholds,
                "mr_shadow_rule_checks": row.mr_shadow_rule_checks,
                "mr_shadow_rule_variant": row.mr_shadow_rule_variant,
                "execution_snapshot_realtime": row.realtime_execution_snapshot,
                "entry_edge_after_execution": row.realtime_edge_diagnostic,
                "entry_live_edge": row.live_edge_status,
                "linked_close": linked_close,
                "linked_positive_outcome": linked_positive,
            }
        )

    blocked_rows = [row for row in row_level_audit if row.get("current_gate_blocked")]
    admitted_rows = [
        row for row in row_level_audit if row.get("final_decision") in {"buy", "sell"}
    ]
    admitted_near_threshold_rows = [
        row
        for row in admitted_rows
        if _is_admitted_near_threshold_bucket(
            row.get("current_margin_bucket"),
            row.get("shadow_margin_bucket"),
        )
    ]
    linked_rows = [row for row in admitted_rows if row.get("linked_close") is not None]
    linked_near_threshold_rows = [
        row
        for row in linked_rows
        if _is_admitted_near_threshold_bucket(
            row.get("current_margin_bucket"),
            row.get("shadow_margin_bucket"),
        )
    ]
    diagnostics = _build_sample_diagnostics(
        row_level_audit=row_level_audit,
        admitted_rows=admitted_rows,
        linked_rows=linked_rows,
        admitted_near_threshold_rows=admitted_near_threshold_rows,
        linked_near_threshold_rows=linked_near_threshold_rows,
    )
    stage_reduction = diagnostics["stage_reduction"]
    blocked_remain_blocked = sum(
        1 for row in blocked_rows if bool(row.get("shadow_gate_blocked"))
    )
    admitted_fail_under_shadow = sum(
        1 for row in admitted_rows if bool(row.get("shadow_gate_blocked"))
    )
    admitted_shadow_counterfactual_raw = sum(
        1 for row in admitted_rows if bool(row.get("shadow_counterfactual_raw"))
    )
    admitted_shadow_counterfactual_partial_history = sum(
        1
        for row in admitted_rows
        if bool(row.get("shadow_counterfactual_raw"))
        and bool(row.get("partial_history_ready"))
    )
    admitted_shadow_counterfactual_no_history = sum(
        1
        for row in admitted_rows
        if bool(row.get("shadow_counterfactual_raw"))
        and not bool(row.get("runtime_history_ready"))
        and not bool(row.get("partial_history_ready"))
    )
    secondary_shadow_effect_ratio = _round_float(
        (
            float(admitted_shadow_counterfactual_raw) / float(len(admitted_rows))
            if admitted_rows
            else None
        )
    )
    shadow_alignment_gap = (
        int(admitted_shadow_counterfactual_raw) - int(admitted_fail_under_shadow)
    )
    current_allowed_near = [
        row
        for row in linked_near_threshold_rows
        if row.get("current_margin_bucket") == NEAR_THRESHOLD_ALLOWED_BUCKET
    ]
    shadow_allowed_near = [
        row
        for row in linked_near_threshold_rows
        if row.get("shadow_margin_bucket") == NEAR_THRESHOLD_ALLOWED_BUCKET
    ]
    current_precision = _round_float(
        _mean(
            [
                1.0 if row.get("linked_positive_outcome") else 0.0
                for row in current_allowed_near
            ]
        )
    )
    shadow_precision = _round_float(
        _mean(
            [
                1.0 if row.get("linked_positive_outcome") else 0.0
                for row in shadow_allowed_near
            ]
        )
    )
    current_bad_allows = sum(
        1
        for row in current_allowed_near
        if row.get("linked_positive_outcome") is False
    )
    shadow_bad_allows = sum(
        1
        for row in shadow_allowed_near
        if row.get("linked_positive_outcome") is False
    )

    summary = {
        "rows_audited": len(row_level_audit),
        "history_ready_rows": sum(
            1 for row in row_level_audit if row.get("history_ready")
        ),
        "runtime_history_ready_rows": sum(
            1 for row in row_level_audit if row.get("runtime_history_ready")
        ),
        "partial_history_ready_rows": sum(
            1 for row in admitted_rows if row.get("partial_history_ready")
        ),
        "blocked_rows": len(blocked_rows),
        "admitted_rows": len(admitted_rows),
        "admitted_near_threshold_rows": len(admitted_near_threshold_rows),
        "broad_near_threshold_rows": int(
            stage_reduction.get("broad_near_threshold_rows") or 0
        ),
        "linkage_eligible_rows": sum(
            1 for row in admitted_rows if row.get("linkage_eligible")
        ),
        "linked_close_support": {
            "open_rows": int(link_stats.get("open_rows") or 0),
            "close_rows": int(link_stats.get("close_rows") or 0),
            "linked_rows": len(linked_rows),
            "linked_share_of_admitted": (
                float(len(linked_rows)) / float(len(admitted_rows))
                if admitted_rows
                else None
            ),
            "linked_near_threshold_rows": len(linked_near_threshold_rows),
            "linked_broad_near_threshold_rows": int(
                stage_reduction.get("linked_broad_near_threshold_rows") or 0
            ),
            "linkage_eligible_rows": int(
                link_stats.get("linkage_eligible_rows") or 0
            ),
            "unlinked_eligible_decisions": int(
                link_stats.get("unlinked_eligible_decisions") or 0
            ),
            "link_failure_reasons": {
                "history_not_ready_rows": int(
                    link_stats.get("history_not_ready_rows") or 0
                ),
                "runtime_history_not_ready_rows": int(
                    link_stats.get("runtime_history_not_ready_rows") or 0
                ),
                "partial_history_ready_rows": int(
                    link_stats.get("partial_history_ready_rows") or 0
                ),
                "missing_candidate_value_rows": int(
                    link_stats.get("missing_candidate_value_rows") or 0
                ),
                "missing_expected_edge_rows": int(
                    link_stats.get("missing_expected_edge_rows") or 0
                ),
                "no_open_symbol_side_match_rows": int(
                    link_stats.get("no_open_symbol_side_match_rows") or 0
                ),
                "missing_open_expected_edge_rows": int(
                    link_stats.get("missing_open_expected_edge_rows") or 0
                ),
                "no_open_expected_edge_match_rows": int(
                    link_stats.get("no_open_expected_edge_match_rows") or 0
                ),
                "missing_open_decision_ts_rows": int(
                    link_stats.get("missing_open_decision_ts_rows") or 0
                ),
                "no_open_timestamp_match_rows": int(
                    link_stats.get("no_open_timestamp_match_rows") or 0
                ),
                "open_missing_trade_id_rows": int(
                    link_stats.get("open_missing_trade_id_rows") or 0
                ),
                "open_missing_close_rows": int(
                    link_stats.get("open_missing_close_rows") or 0
                ),
                "excluded_reason_counts": dict(
                    link_stats.get("excluded_reason_counts") or {}
                ),
            },
        },
        "current_vs_shadow": {
            "blocked_rows_remaining_blocked": blocked_remain_blocked,
            "admitted_rows_that_fail_under_shadow": admitted_fail_under_shadow,
            "admitted_rows_shadow_counterfactual_raw": (
                admitted_shadow_counterfactual_raw
            ),
            "admitted_rows_shadow_counterfactual_partial_history": (
                admitted_shadow_counterfactual_partial_history
            ),
            "admitted_rows_shadow_counterfactual_no_history": (
                admitted_shadow_counterfactual_no_history
            ),
            "secondary_shadow_effect_ratio": secondary_shadow_effect_ratio,
            "shadow_alignment_gap": shadow_alignment_gap,
            "current_formula_precision": current_precision,
            "shadow_formula_precision": shadow_precision,
            "current_formula_bad_allows": current_bad_allows,
            "shadow_formula_bad_allows": shadow_bad_allows,
        },
        "realtime_execution_comparison": build_realtime_comparison(
            row_level_audit
        ),
        "directional_claims": {
            "all_blocked_rows_remain_blocked": (
                blocked_remain_blocked == len(blocked_rows)
            ),
            "subset_of_admitted_rows_would_fail": (
                admitted_fail_under_shadow > 0
                and admitted_fail_under_shadow < len(admitted_rows)
            )
            if admitted_rows
            else False,
            "shadow_better_or_safer_near_threshold": (
                (
                    shadow_precision is not None
                    and current_precision is not None
                    and shadow_precision >= current_precision
                )
                and shadow_bad_allows <= current_bad_allows
            )
            if shadow_precision is not None and current_precision is not None
            else None,
        },
        "diagnostics": diagnostics,
        "by_symbol": _group_rows(row_level_audit, "symbol"),
        "by_side": _group_rows(row_level_audit, "side"),
        "by_seed": _group_rows(row_level_audit, "seed"),
        "by_bucket_source": _group_rows(row_level_audit, "bucket_source"),
    }
    stage.check(
        "aggregated row count matches row-level audit",
        summary["rows_audited"] == len(row_level_audit),
        {"rows_audited": summary["rows_audited"]},
    )
    stage.check(
        "linked close count does not exceed admitted rows",
        summary["linked_close_support"]["linked_rows"] <= summary["admitted_rows"],
        summary["linked_close_support"],
    )
    stage.check(
        "linkage eligible count does not exceed admitted rows",
        summary["linkage_eligible_rows"] <= summary["admitted_rows"],
        stage_reduction,
    )
    stage.check(
        "linked close count does not exceed linkage eligible rows",
        summary["linked_close_support"]["linked_rows"]
        <= summary["linkage_eligible_rows"],
        stage_reduction,
    )
    stage.check(
        "strict near-threshold admitted rows are a subset of broad near-threshold rows",
        (
            summary["admitted_near_threshold_rows"]
            <= summary["broad_near_threshold_rows"]
        ),
        stage_reduction,
    )
    stage.check(
        (
            "linked strict near-threshold rows do not exceed linked broad "
            "near-threshold rows"
        ),
        (
            summary["linked_close_support"]["linked_near_threshold_rows"]
            <= summary["linked_close_support"][
                "linked_broad_near_threshold_rows"
            ]
        ),
        stage_reduction,
    )
    return summary, row_level_audit, stage.finalize()


def validate_sufficiency(
    summary: dict[str, Any],
    fresh_db_count: int,
) -> dict[str, Any]:
    stage = StageRecorder("data_sufficiency")
    thresholds = {
        "fresh_db_count": MIN_FRESH_DB_COUNT,
        "history_ready_rows": MIN_HISTORY_READY_ROWS,
        "admitted_rows": MIN_ADMITTED_ROWS,
        "admitted_near_threshold_rows": MIN_ADMITTED_NEAR_THRESHOLD_ROWS,
        "linked_rows": MIN_LINKED_CLOSES,
        "linked_near_threshold_rows": MIN_LINKED_NEAR_THRESHOLD_ROWS,
    }
    actuals = {
        "fresh_db_count": fresh_db_count,
        "history_ready_rows": summary.get("history_ready_rows"),
        "admitted_rows": summary.get("admitted_rows"),
        "admitted_near_threshold_rows": summary.get("admitted_near_threshold_rows"),
        "linked_rows": (summary.get("linked_close_support") or {}).get("linked_rows"),
        "linked_near_threshold_rows": (
            (summary.get("linked_close_support") or {}).get(
                "linked_near_threshold_rows"
            )
        ),
    }
    for key, minimum in thresholds.items():
        actual = int(actuals.get(key) or 0)
        stage.check(
            f"{key} meets minimum",
            actual >= minimum,
            {"actual": actual, "minimum": minimum},
        )
    result = stage.finalize()
    result["thresholds"] = thresholds
    result["actuals"] = actuals
    return result


def build_integrity_summary(*stages: dict[str, Any]) -> dict[str, Any]:
    return {
        "passed": all(bool(stage.get("passed")) for stage in stages),
        "stages": list(stages),
    }


def classify(
    artifacts: list[FreshArtifacts],
    summary: dict[str, Any],
    integrity: dict[str, Any],
    sufficiency: dict[str, Any],
    runtime_source_stage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_vs_shadow = summary.get("current_vs_shadow") or {}
    directional_claims = summary.get("directional_claims") or {}
    integrity_pass = bool(integrity.get("passed"))
    sufficiency_pass = bool(sufficiency.get("passed"))
    admitted_rows = int(summary.get("admitted_rows") or 0)
    linkage_eligible_rows = int(summary.get("linkage_eligible_rows") or 0)
    primary_fail_subset_size = int(
        current_vs_shadow.get("admitted_rows_that_fail_under_shadow") or 0
    )
    secondary_effect_size = int(
        current_vs_shadow.get("admitted_rows_shadow_counterfactual_raw") or 0
    )
    shadow_effect_alignment = _shadow_effect_alignment(
        primary_fail_subset_size,
        secondary_effect_size,
    )
    linked_near_threshold_rows = int(
        ((summary.get("linked_close_support") or {}).get("linked_near_threshold_rows"))
        or 0
    )
    blocked_direction = bool(directional_claims.get("all_blocked_rows_remain_blocked"))
    admitted_direction = bool(
        directional_claims.get("subset_of_admitted_rows_would_fail")
    )
    near_threshold_safer = directional_claims.get(
        "shadow_better_or_safer_near_threshold"
    )

    enough_for_near_threshold_contradiction = (
        linked_near_threshold_rows >= MIN_LINKED_NEAR_THRESHOLD_ROWS
        and current_vs_shadow.get("current_formula_precision") is not None
        and current_vs_shadow.get("shadow_formula_precision") is not None
    )
    enough_for_admitted_contradiction = admitted_rows >= MIN_ADMITTED_ROWS

    directional_mismatch = False
    directional_mismatch_reasons: list[str] = []
    if integrity_pass and sufficiency_pass:
        if not blocked_direction and int(summary.get("blocked_rows") or 0) > 0:
            directional_mismatch = True
            directional_mismatch_reasons.append(
                "Some current blocked rows no longer remain blocked under shadow."
            )
        if enough_for_admitted_contradiction and not admitted_direction:
            directional_mismatch = True
            directional_mismatch_reasons.append(
                "Valid admitted-row sample contradicts the expected shadow fail subset."
            )
        if enough_for_near_threshold_contradiction and near_threshold_safer is False:
            directional_mismatch = True
            directional_mismatch_reasons.append(
                "Valid linked near-threshold sample shows shadow is not safer "
                "than current."
            )

    operationally_better_or_safer = bool(
        blocked_direction
        and admitted_direction
        and near_threshold_safer is True
        and current_vs_shadow.get("shadow_formula_bad_allows")
        <= current_vs_shadow.get("current_formula_bad_allows")
    )

    if (
        integrity_pass
        and sufficiency_pass
        and not directional_mismatch
        and operationally_better_or_safer
    ):
        verdict = "PREPARE_DISABLED_FLAG_PATCH"
        reason = (
            "Fresh data integrity checks, module/function pipeline validation, and "
            "sample sufficiency all pass; no directional mismatch is present; shadow "
            "behavior is operationally safer than current."
        )
    elif directional_mismatch:
        verdict = "DO_NOT_PROMOTE"
        reason = " ".join(directional_mismatch_reasons)
    elif integrity_pass and sufficiency_pass:
        verdict = "DO_NOT_PROMOTE"
        reason = (
            "Fresh-pass integrity and sample sufficiency cleared, but the shadow "
            "configuration did not demonstrate operational improvement or safety "
            "sufficient for promotion."
        )
    else:
        verdict = "HOLD_FOR_MORE_DATA"
        if not integrity_pass:
            failure_mode = "INTEGRITY_FAILURE"
            reason = (
                "Fresh-pass structural integrity validation failed, so the result "
                "cannot be promoted."
            )
        elif linkage_eligible_rows == 0:
            failure_mode = "LINKAGE_INPUT_EMPTY"
            reason = (
                "Admitted rows were observed, but none qualified as readiness "
                "linkage input after runtime-history and open/close evidence "
                "screening."
            )
        elif not sufficiency_pass:
            failure_mode = "PROMOTION_SAMPLE_INSUFFICIENT"
            reason = (
                "Fresh-pass integrity checks passed, but sample sufficiency thresholds "
                "did not clear for interpretation."
            )
        else:
            failure_mode = None
            reason = (
                "Fresh-pass evidence remains inconclusive even though the pipeline ran "
                "cleanly; keep collecting near-threshold admitted rows."
            )
    if verdict != "HOLD_FOR_MORE_DATA":
        failure_mode = None

    return {
        "artifact_count": len(artifacts),
        "data_integrity_pass": integrity_pass,
        "module_pipeline_integrity_pass": bool(
            (runtime_source_stage or {}).get("passed")
        ),
        "sample_sufficiency_pass": sufficiency_pass,
        "SHADOW_EFFECT_ALIGNMENT": shadow_effect_alignment,
        "PRIMARY_FAIL_SUBSET_SIZE": primary_fail_subset_size,
        "SECONDARY_EFFECT_SIZE": secondary_effect_size,
        "directional_mismatch": directional_mismatch,
        "directional_mismatch_reasons": directional_mismatch_reasons,
        "operationally_better_or_safer": operationally_better_or_safer,
        "final_verdict": verdict,
        "failure_mode": failure_mode,
        "reason": reason,
    }


def analyze_validation_pass(
    artifact_prefix: str,
    stamp: str,
    expected_seeds: set[int] | None = None,
) -> dict[str, Any]:
    fresh_artifacts, discovery_meta = discover_fresh_artifacts(
        artifact_prefix=artifact_prefix,
        stamp=stamp,
        expected_seeds=expected_seeds,
    )
    runtime_source_stage = validate_runtime_source()
    artifact_stage = validate_artifacts(fresh_artifacts, discovery_meta)
    rows, payload_stats, formula_stats, extraction_info = load_decision_rows(
        fresh_artifacts
    )
    extraction_stage = extraction_info["stage"]
    linked_by_key, linkage_meta_by_key, link_stats, link_stage = (
        validate_linked_outcomes(
            fresh_artifacts,
            rows,
        )
    )
    summary, row_level_audit, aggregation_stage = assemble_shadow_audit(
        rows,
        linked_by_key,
        linkage_meta_by_key,
        link_stats,
    )
    integrity = build_integrity_summary(
        runtime_source_stage,
        artifact_stage,
        extraction_stage,
        link_stage,
        aggregation_stage,
    )
    sufficiency = validate_sufficiency(summary, len(fresh_artifacts))
    classifier = classify(
        artifacts=fresh_artifacts,
        summary=summary,
        integrity=integrity,
        sufficiency=sufficiency,
        runtime_source_stage=runtime_source_stage,
    )
    selected_symbols_context = discover_selected_symbols_context(
        artifact_prefix=artifact_prefix,
        stamp=stamp,
    )
    execution_cost_diagnostic_context = discover_execution_cost_diagnostic_context(
        artifact_prefix=artifact_prefix,
        stamp=stamp,
    )
    return {
        "artifact_prefix": artifact_prefix,
        "stamp": stamp,
        "artifacts": fresh_artifacts,
        "discovery_meta": discovery_meta,
        "selected_symbols_context": selected_symbols_context,
        "execution_cost_diagnostic_context": execution_cost_diagnostic_context,
        "runtime_source_stage": runtime_source_stage,
        "artifact_stage": artifact_stage,
        "payload_stats": payload_stats,
        "formula_stats": formula_stats,
        "extraction_stage": extraction_stage,
        "per_db_counts": extraction_info["per_db_counts"],
        "link_stats": link_stats,
        "link_stage": link_stage,
        "summary": summary,
        "realtime_comparison": summary.get("realtime_execution_comparison") or {},
        "row_level_audit": row_level_audit,
        "aggregation_stage": aggregation_stage,
        "integrity": integrity,
        "sufficiency": sufficiency,
        "classification": classifier,
    }


def build_execution_cost_diagnostic_payload(state: dict[str, Any]) -> dict[str, Any]:
    row_level = state.get("row_level_audit") or []
    realtime_comparison = state.get("realtime_comparison") or {}
    threshold_validation_rows = []
    for row in row_level:
        live_edge = row.get("entry_live_edge") or {}
        snapshot = row.get("execution_snapshot_realtime") or {}
        threshold = _safe_float(row.get("active_threshold"))
        realtime_edge = _snapshot_float(snapshot, "edge_after_realtime_cost")
        if not bool(live_edge.get("pass")) or not bool(row.get("current_gate_blocked")):
            continue
        threshold_validation_rows.append(
            {
                "symbol": row.get("symbol"),
                "bucket_source": row.get("bucket_source"),
                "current_gate_blocked": bool(row.get("current_gate_blocked")),
                "shadow_gate_blocked": bool(row.get("shadow_gate_blocked")),
                "realtime_confirms_block": bool(
                    threshold is not None
                    and realtime_edge is not None
                    and float(realtime_edge) < float(threshold)
                ),
                "realtime_rejects_block": bool(
                    threshold is not None
                    and realtime_edge is not None
                    and float(realtime_edge) >= float(threshold)
                ),
                "threshold": _round_float(threshold),
                "realtime_edge_after_cost": _round_float(realtime_edge),
            }
        )
    return {
        "artifact_prefix": state.get("artifact_prefix"),
        "stamp": state.get("stamp"),
        "selected_symbols_context": state.get("selected_symbols_context") or {},
        "validation": {
            "data_integrity": state.get("integrity") or {},
            "sufficiency": state.get("sufficiency") or {},
            "module_function_correctness": {
                "runtime_semantics_stage": state.get("runtime_source_stage") or {},
                "formula_metrics": state.get("formula_stats") or {},
            },
            "execution_cost_realism_checks": realtime_comparison,
        },
        "realtime_comparison": realtime_comparison,
        "threshold_validation_rows": threshold_validation_rows[:25],
        "final_classification": state.get("classification") or {},
    }


def write_execution_cost_diagnostic_artifacts(
    state: dict[str, Any],
) -> dict[str, str]:
    payload = build_execution_cost_diagnostic_payload(state)
    json_path = _execution_cost_diagnostic_json_path(
        state["artifact_prefix"],
        state["stamp"],
    )
    md_path = _execution_cost_diagnostic_md_path(
        state["artifact_prefix"],
        state["stamp"],
    )
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    realtime = payload["realtime_comparison"]
    lines = [
        "EXECUTION_COST_DIAGNOSTIC",
        "",
        f"artifact_prefix: {state['artifact_prefix']}",
        f"stamp: {state['stamp']}",
        (
            "selected_symbols: "
            f"{','.join(
                (state.get('selected_symbols_context') or {}).get(
                    'selected_symbols'
                ) or []
            )}"
        ),
        "",
        "EXECUTION_COST_REALISM_CHECKS",
        (
            "current_fee_only_optimistic_vs_realtime_share: "
            f"{realtime.get('current_fee_only_optimistic_vs_realtime_share')}"
        ),
        (
            "shadow_cost_optimistic_vs_realtime_share: "
            f"{realtime.get('shadow_cost_optimistic_vs_realtime_share')}"
        ),
        (
            "shadow_closer_to_realtime_share: "
            f"{realtime.get('shadow_closer_to_realtime_share')}"
        ),
        (
            "mean_cost_model_error_vs_shadow: "
            f"{realtime.get('mean_cost_model_error_vs_shadow')}"
        ),
        (
            "mean_cost_model_error_vs_fee_only: "
            f"{realtime.get('mean_cost_model_error_vs_fee_only')}"
        ),
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json_path": str(json_path), "md_path": str(md_path)}


def build_selection_boundary_payload(state: dict[str, Any]) -> dict[str, Any]:
    selection_method = (state.get("selected_symbols_context") or {}).get(
        "selection_method"
    )
    return {
        "upstream_candidate_selection": {
            "module": "Alpha_Zol0-lvl_5-main/core/volatility_rotation.py",
            "functions": [
                "build_top_scalping_pairs",
                "_classify_symbol",
                "main",
            ],
            "native_selector_outputs": ["KEEP", "WATCH", "DROP"],
            "allowed_selector_outputs": {
                "WATCH": (
                    "Ranked candidate only. Selection evidence, not runtime "
                    "admission and not promotion evidence."
                ),
                "EVIDENCE_RUN": (
                    "Symbol copied into selected_symbols_context and passed to "
                    "RUN_SYMBOLS for a batch evidence run."
                ),
                "REJECT_FOR_NOW": (
                    "Symbol dropped or excluded by selector output and not passed "
                    "into the batch run universe."
                ),
            },
        },
        "batch_symbol_routing": {
            "module": "DataAnalysisExpert/shadow_promotion_pipeline_lib.py",
            "functions": [
                "resolve_selected_symbols",
                "build_fresh_validation_batch",
                "run_seed_batch",
            ],
            "selection_method": selection_method,
            "artifact_path": (state.get("selected_symbols_context") or {}).get(
                "artifact_path"
            ),
            "bypass_modes": [
                "explicit_run_symbols",
                "default_wrapper_symbols",
            ],
        },
        "runtime_admission_logic": {
            "modules": [
                "DataAnalysisExpert/phase4b_run_seed.ps1",
                "DataAnalysisExpert/run_11_paper_v2.py",
                "Alpha_Zol0-lvl_5-main/core/BotCore.py",
            ],
            "functions": [
                "phase4b_run_seed.ps1 parameter RunSymbols",
                "BotCore.run_bot",
                "BotCore._apply_entry_alpha_selector",
            ],
            "runtime_gate_start": (
                "BotCore.run_bot begins symbol iteration after RUN_SYMBOLS is "
                "resolved from environment or config."
            ),
        },
        "classifier_promotion_logic": {
            "module": "DataAnalysisExpert/shadow_promotion_pipeline_lib.py",
            "functions": [
                "validate_sufficiency",
                "classify",
                "write_outputs",
            ],
            "allowed_verdicts": sorted(ALLOWED_VERDICTS),
        },
        "blocked_interpretations": [
            "PROMOTE_NOW",
            "AUTO_ENABLE",
            "PRODUCTION_READY",
        ],
    }


def build_audit_payload(
    run_specs: list[RunSpec],
    state: dict[str, Any],
) -> dict[str, Any]:
    effective_run_specs = run_specs or [
        RunSpec(
            seed=artifact.seed,
            ticks_per_run=(
                _extract_ticks_per_run_from_wrapper_log(artifact.wrapper_log)
                or DEFAULT_RECOVERY_TICKS_PER_RUN
            ),
            tick_sleep_sec=1.0,
        )
        for artifact in state["artifacts"]
    ]
    report_metadata = build_report_metadata(
        report_type="edge_over_fee_shadow_promotion_readiness_audit",
        artifact_prefix=state["artifact_prefix"],
        stamp=state["stamp"],
    )
    return {
        "report_metadata": report_metadata,
        "pipeline_run": {
            "artifact_prefix": state["artifact_prefix"],
            "stamp": state["stamp"],
            "run_specs": [
                {
                    "seed": run_spec.seed,
                    "ticks_per_run": run_spec.ticks_per_run,
                    "tick_sleep_sec": run_spec.tick_sleep_sec,
                }
                for run_spec in effective_run_specs
            ],
            "fresh_db_paths": [
                str(artifact.db_path) for artifact in state["artifacts"]
            ],
            "selected_symbols_context": state["selected_symbols_context"],
            "execution_cost_diagnostic_context": state[
                "execution_cost_diagnostic_context"
            ],
            "selection_boundary": build_selection_boundary_payload(state),
        },
        "validation": {
            "data_integrity": state["integrity"],
            "sufficiency": state["sufficiency"],
            "module_pipeline_correctness": {
                "passed": bool(state["runtime_source_stage"].get("passed")),
                "runtime_semantics_stage": state["runtime_source_stage"],
            },
            "artifact_metrics": state["payload_stats"],
            "formula_metrics": state["formula_stats"],
            "link_metrics": state["link_stats"],
            "realtime_execution_comparison": state["realtime_comparison"],
        },
        "shadow_audit": {
            "summary": state["summary"],
            "row_level_audit": state["row_level_audit"],
        },
        "classification": state["classification"],
    }


def build_report_metadata(
    report_type: str,
    artifact_prefix: str,
    stamp: str,
) -> dict[str, Any]:
    baseline_or_fresh_pass = "standalone"
    evaluation_mode = "official_history_gated_runtime_validation"
    canonical_source_of_truth = f"{artifact_prefix} / {stamp}"
    why_this_verdict_differs = "This report is the canonical report for its stamp."
    canonical_source_path = None
    generic_alias_role = "generic alias follows this report"
    stamp_specific_output_role = "stamp-specific output is the canonical output"
    if artifact_prefix == PHASE95_ARTIFACT_PREFIX:
        canonical_source_of_truth = (
            f"{PHASE95_ARTIFACT_PREFIX} / {PHASE95_BASELINE_STAMP}"
        )
        canonical_source_path = str(
            AUTOPSY / "phase95_repaired_medium_closeout_20260317.md"
        )
        generic_alias_role = (
            "generic alias is reserved for the canonical baseline source of truth"
        )
        if stamp == PHASE95_BASELINE_STAMP:
            baseline_or_fresh_pass = "baseline"
            stamp_specific_output_role = (
                "stamp-specific output mirrors the canonical baseline and also owns "
                "the generic alias"
            )
            why_this_verdict_differs = (
                "This baseline stamp is the repo-authoritative promotion-readiness "
                "source of truth for phase95."
            )
        elif stamp == PHASE95_FRESH_STAMP:
            baseline_or_fresh_pass = "fresh_pass"
            stamp_specific_output_role = (
                "stamp-specific output is fresh-pass evidence only and must not "
                "overwrite the generic alias"
            )
            why_this_verdict_differs = (
                "This fresh pass is evidence-only. It may differ from the baseline "
                "source-of-truth verdict because recovered sidecars, sparse linkage, "
                "and sample sufficiency are evaluated for this stamp separately."
            )
        else:
            baseline_or_fresh_pass = "phase95_other"
            stamp_specific_output_role = (
                "stamp-specific output is supplemental evidence only and must not "
                "overwrite the generic alias"
            )
            why_this_verdict_differs = (
                "This phase95 stamp is not the canonical baseline. Use it as "
                "supplemental evidence against the baseline source of truth."
            )
    return {
        "report_type": report_type,
        "evaluation_mode": evaluation_mode,
        "canonical_source_of_truth": canonical_source_of_truth,
        "canonical_source_path": canonical_source_path,
        "baseline_or_fresh_pass": baseline_or_fresh_pass,
        "generic_alias_role": generic_alias_role,
        "stamp_specific_output_role": stamp_specific_output_role,
        "why_this_verdict_differs_from_other_reports": why_this_verdict_differs,
    }


def _stamp_specific_readiness_paths(
    artifact_prefix: str,
    stamp: str,
) -> tuple[Path, Path]:
    audit_name = (
        f"{artifact_prefix}_{stamp}_"
        "edge_over_fee_shadow_promotion_readiness_audit.json"
    )
    report_name = (
        f"{artifact_prefix}_{stamp}_"
        "edge_over_fee_shadow_promotion_readiness_report.md"
    )
    return (
        ANALYSIS / audit_name,
        AUTOPSY / report_name,
    )


def write_outputs(
    run_specs: list[RunSpec],
    state: dict[str, Any],
) -> tuple[Path, Path]:
    state["formula_provenance_artifacts"] = write_formula_provenance_artifacts()
    state["execution_cost_diagnostic_artifacts"] = (
        write_execution_cost_diagnostic_artifacts(state)
    )
    state["execution_cost_diagnostic_context"] = (
        discover_execution_cost_diagnostic_context(
            state["artifact_prefix"],
            state["stamp"],
        )
    )
    audit = build_audit_payload(run_specs, state)
    summary = state["summary"]
    classifier = state["classification"]
    report_metadata = audit["report_metadata"]
    analysis_path = ANALYSIS / "edge_over_fee_shadow_promotion_readiness_audit.json"
    report_path = AUTOPSY / "edge_over_fee_shadow_promotion_readiness_report.md"
    stamp_analysis_path, stamp_report_path = _stamp_specific_readiness_paths(
        state["artifact_prefix"],
        state["stamp"],
    )
    use_generic_aliases = True
    primary_analysis_path = analysis_path
    primary_report_path = report_path
    if state["artifact_prefix"] == PHASE95_ARTIFACT_PREFIX:
        primary_analysis_path = stamp_analysis_path
        primary_report_path = stamp_report_path
        use_generic_aliases = state["stamp"] == PHASE95_BASELINE_STAMP
    ANALYSIS.mkdir(parents=True, exist_ok=True)
    AUTOPSY.mkdir(parents=True, exist_ok=True)
    audit_text = json.dumps(audit, indent=2)
    stamp_analysis_path.write_text(audit_text, encoding="utf-8")
    if use_generic_aliases:
        analysis_path.write_text(audit_text, encoding="utf-8")

    linked_close_support = summary.get("linked_close_support") or {}
    current_vs_shadow = summary.get("current_vs_shadow") or {}
    realtime_comparison = state.get("realtime_comparison") or {}
    selection_boundary = build_selection_boundary_payload(state)
    report_lines = [
        "EDGE_OVER_FEE_SHADOW_PROMOTION_READINESS_REPORT",
        "",
        "REPORT_METADATA",
        f"report_type: {report_metadata['report_type']}",
        f"evaluation_mode: {report_metadata['evaluation_mode']}",
        (
            "canonical_source_of_truth: "
            f"{report_metadata['canonical_source_of_truth']}"
        ),
        (
            "canonical_source_path: "
            f"{report_metadata['canonical_source_path']}"
        ),
        (
            "baseline_or_fresh_pass: "
            f"{report_metadata['baseline_or_fresh_pass']}"
        ),
        (
            "generic_alias_role: "
            f"{report_metadata['generic_alias_role']}"
        ),
        (
            "stamp_specific_output_role: "
            f"{report_metadata['stamp_specific_output_role']}"
        ),
        (
            "why_this_verdict_differs_from_other_reports: "
            f"{report_metadata['why_this_verdict_differs_from_other_reports']}"
        ),
        "",
        "VALIDATION_SECTION",
        f"artifact_prefix: {state['artifact_prefix']}",
        f"stamp: {state['stamp']}",
        f"fresh_db_count: {len(state['artifacts'])}",
        (
            "selected_symbols_artifact_path: "
            f"{state['selected_symbols_context'].get('artifact_path')}"
        ),
        (
            "selection_method: "
            f"{state['selected_symbols_context'].get('selection_method')}"
        ),
        (
            "selected_symbols: "
            f"{','.join(
                state['selected_symbols_context'].get('selected_symbols') or []
            )}"
        ),
        (
            "execution_cost_diagnostic_json: "
            f"{state['execution_cost_diagnostic_context'].get('json_path')}"
        ),
        f"data_integrity_pass: {state['integrity'].get('passed')}",
        (
            "module_pipeline_integrity_pass: "
            f"{classifier.get('module_pipeline_integrity_pass')}"
        ),
        f"sample_sufficiency_pass: {classifier.get('sample_sufficiency_pass')}",
        "",
        "SELECTION_BOUNDARY",
        (
            "selector_module: "
            f"{selection_boundary['upstream_candidate_selection']['module']}"
        ),
        (
            "selector_functions: "
            + ",".join(
                selection_boundary["upstream_candidate_selection"]["functions"]
            )
        ),
        "native_selector_outputs: KEEP,WATCH,DROP",
        "allowed_selector_outputs: WATCH,EVIDENCE_RUN,REJECT_FOR_NOW",
        (
            "WATCH: ranked candidate only; not runtime admission and not promotion "
            "evidence"
        ),
        (
            "EVIDENCE_RUN: symbol routed into RUN_SYMBOLS for validation batch "
            "execution"
        ),
        "REJECT_FOR_NOW: excluded or dropped by selector and not routed into batch",
        (
            "batch_routing_functions: "
            + ",".join(selection_boundary["batch_symbol_routing"]["functions"])
        ),
        (
            "runtime_gate_start: "
            f"{selection_boundary['runtime_admission_logic']['runtime_gate_start']}"
        ),
        (
            "classifier_functions: "
            + ",".join(
                selection_boundary["classifier_promotion_logic"]["functions"]
            )
        ),
        "blocked_interpretations: PROMOTE_NOW,AUTO_ENABLE,PRODUCTION_READY",
        "",
        "DATA_COMPLETENESS_AND_SUFFICIENCY",
        f"history_ready_rows: {summary.get('history_ready_rows')}",
        f"runtime_history_ready_rows: {summary.get('runtime_history_ready_rows')}",
        f"partial_history_ready_rows: {summary.get('partial_history_ready_rows')}",
        f"admitted_rows: {summary.get('admitted_rows')}",
        f"admitted_near_threshold_rows: {summary.get('admitted_near_threshold_rows')}",
        f"broad_near_threshold_rows: {summary.get('broad_near_threshold_rows')}",
        f"linkage_eligible_rows: {summary.get('linkage_eligible_rows')}",
        f"open_rows: {linked_close_support.get('open_rows')}",
        f"close_rows: {linked_close_support.get('close_rows')}",
        f"linked_rows: {linked_close_support.get('linked_rows')}",
        (
            "linked_near_threshold_rows: "
            f"{linked_close_support.get('linked_near_threshold_rows')}"
        ),
        (
            "linked_broad_near_threshold_rows: "
            f"{linked_close_support.get('linked_broad_near_threshold_rows')}"
        ),
        (
            "unlinked_eligible_decisions: "
            f"{linked_close_support.get('unlinked_eligible_decisions')}"
        ),
        (
            "link_failure_reasons: "
            + json.dumps(
                linked_close_support.get("link_failure_reasons") or {},
                sort_keys=True,
            )
        ),
        (
            "stage_reduction: "
            + json.dumps(
                (summary.get("diagnostics") or {}).get("stage_reduction") or {},
                sort_keys=True,
            )
        ),
        (
            "admitted_current_bucket_distribution: "
            + json.dumps(
                (
                    (summary.get("diagnostics") or {}).get("bucket_distributions") or {}
                ).get("admitted_current_margin_buckets")
                or {},
                sort_keys=True,
            )
        ),
        (
            "linked_current_bucket_distribution: "
            + json.dumps(
                (
                    (summary.get("diagnostics") or {}).get("bucket_distributions") or {}
                ).get("linked_current_margin_buckets")
                or {},
                sort_keys=True,
            )
        ),
        "",
        "CURRENT_VS_SHADOW_AUDIT",
        (
            "blocked_rows_remaining_blocked: "
            f"{current_vs_shadow.get('blocked_rows_remaining_blocked')}"
        ),
        (
            "admitted_rows_that_fail_under_shadow: "
            f"{current_vs_shadow.get('admitted_rows_that_fail_under_shadow')}"
        ),
        (
            "admitted_rows_shadow_counterfactual_raw: "
            f"{current_vs_shadow.get('admitted_rows_shadow_counterfactual_raw')}"
        ),
        (
            "admitted_rows_shadow_counterfactual_partial_history: "
            f"{current_vs_shadow.get(
                'admitted_rows_shadow_counterfactual_partial_history'
            )}"
        ),
        (
            "admitted_rows_shadow_counterfactual_no_history: "
            f"{current_vs_shadow.get('admitted_rows_shadow_counterfactual_no_history')}"
        ),
        (
            "secondary_shadow_effect_ratio: "
            f"{current_vs_shadow.get('secondary_shadow_effect_ratio')}"
        ),
        (
            "shadow_alignment_gap: "
            f"{current_vs_shadow.get('shadow_alignment_gap')}"
        ),
        (
            "current_formula_precision: "
            f"{current_vs_shadow.get('current_formula_precision')}"
        ),
        (
            "shadow_formula_precision: "
            f"{current_vs_shadow.get('shadow_formula_precision')}"
        ),
        (
            "current_formula_bad_allows: "
            f"{current_vs_shadow.get('current_formula_bad_allows')}"
        ),
        (
            "shadow_formula_bad_allows: "
            f"{current_vs_shadow.get('shadow_formula_bad_allows')}"
        ),
        "",
        "SHADOW_EFFECT_ALIGNMENT_ANALYSIS",
        (
            "SHADOW_EFFECT_ALIGNMENT: "
            f"{classifier.get('SHADOW_EFFECT_ALIGNMENT')}"
        ),
        (
            "PRIMARY_FAIL_SUBSET_SIZE: "
            f"{classifier.get('PRIMARY_FAIL_SUBSET_SIZE')}"
        ),
        (
            "SECONDARY_EFFECT_SIZE: "
            f"{classifier.get('SECONDARY_EFFECT_SIZE')}"
        ),
        (
            "interpretation: primary promotion-grade evidence uses only "
            "history_ready=true and shadow_gate_blocked=true; secondary "
            "shadow counterfactual evidence is diagnostic only and does not "
            "change promotion criteria or the final verdict."
        ),
        "",
        "REALTIME_EXECUTION_COMPARISON",
        (
            "rows_with_history_and_realtime_snapshot: "
            f"{realtime_comparison.get('rows_with_history_and_realtime_snapshot')}"
        ),
        (
            "rows_cost_comparable: "
            f"{realtime_comparison.get('rows_cost_comparable')}"
        ),
        (
            "mean_current_fee_only_cost: "
            f"{realtime_comparison.get('mean_current_fee_only_cost')}"
        ),
        (
            "mean_shadow_cost: "
            f"{realtime_comparison.get('mean_shadow_cost')}"
        ),
        (
            "mean_realtime_cost: "
            f"{realtime_comparison.get('mean_realtime_cost')}"
        ),
        (
            "current_fee_only_optimistic_vs_realtime_share: "
            f"{realtime_comparison.get(
                'current_fee_only_optimistic_vs_realtime_share'
            )}"
        ),
        (
            "shadow_cost_optimistic_vs_realtime_share: "
            f"{realtime_comparison.get('shadow_cost_optimistic_vs_realtime_share')}"
        ),
        (
            "shadow_closer_to_realtime_share: "
            f"{realtime_comparison.get('shadow_closer_to_realtime_share')}"
        ),
        (
            "mean_cost_model_error_vs_shadow: "
            f"{realtime_comparison.get('mean_cost_model_error_vs_shadow')}"
        ),
        (
            "mean_cost_model_error_vs_fee_only: "
            f"{realtime_comparison.get('mean_cost_model_error_vs_fee_only')}"
        ),
        "",
        "FINAL_VERDICT",
        str(classifier.get("final_verdict")),
        str(classifier.get("failure_mode")),
        str(classifier.get("reason")),
        "",
    ]
    report_text = "\n".join(report_lines)
    stamp_report_path.write_text(report_text, encoding="utf-8")
    if use_generic_aliases:
        report_path.write_text(report_text, encoding="utf-8")
    return primary_analysis_path, primary_report_path


def run_pipeline_end_to_end(
    run_specs: list[RunSpec],
    artifact_prefix: str,
    stamp: str,
    python_exe: str,
    run_symbols: list[str] | None = None,
    scanner_output_path: str | None = None,
    scanner_top_n: int = 0,
    entry_meanreversion_enable: str | None = None,
) -> dict[str, Any]:
    build_fresh_validation_batch(
        run_specs=run_specs,
        artifact_prefix=artifact_prefix,
        stamp=stamp,
        python_exe=python_exe,
        run_symbols=run_symbols,
        scanner_output_path=scanner_output_path,
        scanner_top_n=scanner_top_n,
        entry_meanreversion_enable=entry_meanreversion_enable,
    )
    state = analyze_validation_pass(
        artifact_prefix=artifact_prefix,
        stamp=stamp,
        expected_seeds={run_spec.seed for run_spec in run_specs},
    )
    analysis_path, report_path = write_outputs(run_specs=run_specs, state=state)
    output = {
        "analysis_path": str(analysis_path),
        "report_path": str(report_path),
        "selected_symbols_artifact_path": (
            state["selected_symbols_context"].get("artifact_path")
        ),
        "execution_cost_diagnostic_json": (
            state["execution_cost_diagnostic_context"].get("json_path")
        ),
        "execution_cost_diagnostic_md": (
            state["execution_cost_diagnostic_context"].get("md_path")
        ),
        "formula_provenance_json": (
            state.get("formula_provenance_artifacts") or {}
        ).get("json_path"),
        "formula_provenance_md": (
            state.get("formula_provenance_artifacts") or {}
        ).get("md_path"),
        "selected_symbols": state["selected_symbols_context"].get(
            "selected_symbols"
        ),
        "entry_meanreversion_enable": entry_meanreversion_enable,
        "final_verdict": state["classification"].get("final_verdict"),
        "failure_mode": state["classification"].get("failure_mode"),
        "reason": state["classification"].get("reason"),
    }
    if output["final_verdict"] not in ALLOWED_VERDICTS:
        raise RuntimeError(f"Unexpected verdict: {output['final_verdict']}")
    return output


def normalize_run_symbols(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    values = [item.strip().upper() for item in str(raw).split(",") if item.strip()]
    return values or None


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2))


def default_python_exe() -> str:
    return sys.executable
