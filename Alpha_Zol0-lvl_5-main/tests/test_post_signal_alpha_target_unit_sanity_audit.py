from __future__ import annotations

import json
from pathlib import Path

from scripts.post_signal_alpha_target_unit_sanity_audit import (
    CLASS_BLOCKED,
    CLASS_CONSISTENT,
    CLASS_INCONCLUSIVE,
    CLASS_MISMATCH,
    analyze_unit_sanity,
)


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _runtime_artifact(target: float = 0.12, *, target_unit: str | None = None) -> dict:
    inputs = {
        "min_p95_signed_net": target,
        "min_samples": 20,
        "runtime_source_required": "rolling_quote_window",
    }
    if target_unit is not None:
        inputs["min_p95_signed_net_unit"] = target_unit
    return {
        "classification": "POST_SIGNAL_TRAJECTORY_NO_TARGETS",
        "inputs": inputs,
        "summary": {
            "trajectory_event_count": 1,
            "clean_event_count": 1,
            "contaminated_event_count": 0,
            "alpha_target_count": 0,
        },
        "ranked_family_buckets": [
            {
                "canonical_strategy": "MEANREVERSION",
                "symbol": "BNBUSDTM",
                "side": "sell",
                "horizon_ticks": 1,
                "sample_count": 1,
                "p95_signed_net_move": 0.000510836592,
                "max_signed_net_move": 0.000510836592,
            }
        ],
    }


def _failure_artifact(*, include_best_event: bool = True) -> dict:
    best_event = {
        "symbol": "BNBUSDTM",
        "canonical_strategy": "MEANREVERSION",
        "side": "sell",
        "horizon_ticks": 1,
        "signed_gross_move": 0.000762476326,
        "estimated_cost": 0.000251639734,
        "signed_net_move": 0.000510836592,
        "mfe": 0.000762476326,
        "mae": 0.0,
        "mfe_minus_cost": 0.000510836592,
        "expected_net_after_cost": 0.00013228466239148903,
        "source": "rolling_quote_window",
    }
    return {
        "classification": "POST_SIGNAL_NO_TARGETS_BECAUSE_SIGNALS_WEAK",
        "inputs": {
            "min_p95_signed_net": 0.12,
            "min_samples": 20,
            "runtime_source_required": "rolling_quote_window",
        },
        "summary": {
            "trajectory_event_count": 1,
            "clean_event_count": 1,
            "contaminated_event_count": 0,
            "alpha_target_count": 0,
        },
        "near_target_counts": {"25pct": 0, "50pct": 0, "75pct": 0, "90pct": 0},
        "best_20_trajectory_events_by_net_opportunity": [best_event] if include_best_event else [],
        "missing_field_counts": {
            "symbol": 0,
            "canonical_strategy": 0,
            "side": 0,
            "source": 0,
            "horizon_ticks": 0,
            "signed_gross_move": 0,
            "estimated_cost": 0,
            "signed_net_move": 0,
            "expected_net_after_cost": 0,
        },
    }


def _source_files(tmp_path: Path) -> dict[str, Path]:
    tracker = tmp_path / "post_signal_trajectory.py"
    runtime_analyzer = tmp_path / "analyze_runtime_post_signal_trajectory.py"
    failure_analyzer = tmp_path / "analyze_post_signal_alpha_target_failure.py"
    tracker.write_text(
        "\n".join(
            [
                "raw_move = (float(quote.mid) - start_mid) / start_mid",
                "signed_gross_move = raw_move if candidate.side == 'buy' else -raw_move",
                "estimated_cost = _estimated_cost(candidate)",
                "signed_net_move = signed_gross_move - estimated_cost",
                "total = breakdown.get('total_cost_ratio')",
                "expected_net_after_cost = candidate.expected_net_after_cost",
            ]
        ),
        encoding="utf-8",
    )
    runtime_analyzer.write_text(
        "\n".join(
            [
                "def analyze_db_paths(db_paths, *, min_p95_signed_net: float = 0.12):",
                "p95_signed_net_move = _percentile(values, 0.95)",
                "and row['p95_signed_net_move'] >= float(min_p95_signed_net)",
            ]
        ),
        encoding="utf-8",
    )
    failure_analyzer.write_text(
        "\n".join(
            [
                "mfe = max(gross, 0.0)",
                "mae = abs(min(gross, 0.0))",
                "mfe_minus_cost = mfe - cost",
                "target = float(inputs.get('min_p95_signed_net', 0.12))",
            ]
        ),
        encoding="utf-8",
    )
    return {
        "tracker": tracker,
        "runtime_analyzer": runtime_analyzer,
        "failure_analyzer": failure_analyzer,
    }


def test_ratio_trajectory_values_compared_to_ratio_target_are_consistent(tmp_path: Path) -> None:
    runtime_path = tmp_path / "runtime.json"
    failure_path = tmp_path / "failure.json"
    _write(runtime_path, _runtime_artifact())
    _write(failure_path, _failure_artifact())

    report = analyze_unit_sanity(runtime_path, failure_path, source_files=_source_files(tmp_path))

    assert report["classification"] == CLASS_CONSISTENT
    assert report["unit_findings"]["signed_net_move"]["unit"] == "ratio"
    assert report["unit_findings"]["alpha_target"]["unit"] == "ratio"
    assert report["normalization_check"]["best_event_remains_far_from_target"] is True


def test_usdt_target_compared_to_ratio_net_opportunity_is_mismatch(tmp_path: Path) -> None:
    runtime_path = tmp_path / "runtime.json"
    failure_path = tmp_path / "failure.json"
    _write(runtime_path, _runtime_artifact(target_unit="USDT"))
    _write(failure_path, _failure_artifact())

    report = analyze_unit_sanity(runtime_path, failure_path, source_files=_source_files(tmp_path))

    assert report["classification"] == CLASS_MISMATCH
    assert report["unit_findings"]["alpha_target"]["unit"] == "USDT"
    assert report["comparison_compatibility"]["p95_signed_net_vs_alpha_target"] is False


def test_missing_full_cost_fields_blocks_usdt_normalization(tmp_path: Path) -> None:
    runtime_path = tmp_path / "runtime.json"
    failure_path = tmp_path / "failure.json"
    _write(runtime_path, _runtime_artifact(target_unit="USDT"))
    failure = _failure_artifact()
    failure["best_20_trajectory_events_by_net_opportunity"][0].pop("expected_net_after_cost")
    failure["missing_field_counts"]["expected_net_after_cost"] = 1
    _write(failure_path, failure)

    report = analyze_unit_sanity(runtime_path, failure_path, source_files=_source_files(tmp_path))

    assert report["classification"] == CLASS_BLOCKED
    assert "expected_net_after_cost" in report["blocking_missing_fields"]


def test_absent_artifacts_are_inconclusive(tmp_path: Path) -> None:
    report = analyze_unit_sanity(
        tmp_path / "missing_runtime.json",
        tmp_path / "missing_failure.json",
        source_files=_source_files(tmp_path),
    )

    assert report["classification"] == CLASS_INCONCLUSIVE
