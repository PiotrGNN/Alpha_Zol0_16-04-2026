from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.analyze_post_signal_alpha_target_failure import (
    CLASS_MISSING_FIELDS,
    CLASS_SAMPLE_TOO_SMALL,
    CLASS_SIGNALS_WEAK,
    analyze_post_signal_alpha_target_failure,
)


def _write_runtime_artifact(path: Path, db_path: Path, *, min_samples: int = 2, target: float = 0.12) -> None:
    path.write_text(
        json.dumps(
            {
                "classification": "POST_SIGNAL_TRAJECTORY_NO_TARGETS",
                "inputs": {
                    "db_paths": [str(db_path)],
                    "min_samples": min_samples,
                    "min_p95_signed_net": target,
                    "runtime_source_required": "rolling_quote_window",
                },
                "summary": {
                    "trajectory_event_count": 0,
                    "clean_event_count": 0,
                    "contaminated_event_count": 0,
                    "alpha_target_count": 0,
                },
                "alpha_targets": [],
                "ranked_family_buckets": [],
            }
        ),
        encoding="utf-8",
    )


def _write_db(path: Path, payloads: list[dict]) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE logs (timestamp TEXT, event TEXT, details TEXT)")
        for idx, payload in enumerate(payloads):
            conn.execute(
                "INSERT INTO logs (timestamp, event, details) VALUES (?, ?, ?)",
                (f"2026-06-04T00:00:{idx:02d}", "post_signal_trajectory_v2", json.dumps(payload)),
            )
        conn.commit()
    finally:
        conn.close()


def _payload(
    strategy: str,
    symbol: str,
    side: str,
    horizon: int,
    gross: float,
    cost: float = 0.001,
    *,
    expected_net: float = 0.02,
    contaminated: bool = False,
) -> dict:
    return {
        "symbol": symbol,
        "strategy": strategy,
        "canonical_strategy": strategy,
        "side": side,
        "source": "rolling_quote_window",
        "horizon_ticks": horizon,
        "signed_gross_move": gross,
        "estimated_cost": cost,
        "signed_net_move": gross - cost,
        "expected_move": expected_net + cost,
        "expected_net_after_cost": expected_net,
        "reason_code": "below_min_net",
        "contamination_flags": {"seed": int(contaminated), "fallback": 0, "mock": 0, "force_open": 0, "forced_cycle": 0},
    }


def test_classifies_clean_but_far_below_relaxed_targets_as_weak_signals(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    artifact_path = tmp_path / "runtime_post_signal.json"
    payloads = [
        _payload("MOMENTUM", "SOLUSDTM", "sell", 5, 0.006),
        _payload("MOMENTUM", "SOLUSDTM", "sell", 5, 0.004),
        _payload("TRENDFOLLOWING", "BTCUSDTM", "buy", 5, 0.003),
    ]
    _write_db(db_path, payloads)
    _write_runtime_artifact(artifact_path, db_path)

    report = analyze_post_signal_alpha_target_failure(artifact_path)

    assert report["classification"] == CLASS_SIGNALS_WEAK
    assert report["summary"]["alpha_target_count"] == 0
    assert report["near_target_counts"]["25pct"] == 0
    assert report["best_events_by_net_opportunity"][0]["canonical_strategy"] == "MOMENTUM"
    assert report["strategy_family_comparison"]["best_non_trendfollowing_net"] > report["strategy_family_comparison"]["best_trendfollowing_net"]


def test_missing_required_trajectory_fields_dominates_classification(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    artifact_path = tmp_path / "runtime_post_signal.json"
    _write_db(
        db_path,
        [
            {
                "symbol": "BNBUSDTM",
                "strategy": "MEANREVERSION",
                "canonical_strategy": "MEANREVERSION",
                "side": "sell",
                "source": "rolling_quote_window",
                "horizon_ticks": 1,
                "contamination_flags": {"seed": 0, "fallback": 0, "mock": 0, "force_open": 0, "forced_cycle": 0},
            }
        ],
    )
    _write_runtime_artifact(artifact_path, db_path)

    report = analyze_post_signal_alpha_target_failure(artifact_path)

    assert report["classification"] == CLASS_MISSING_FIELDS
    assert report["missing_field_counts"]["signed_net_move"] == 1
    assert report["missing_field_counts"]["signed_gross_move"] == 1


def test_small_clean_sample_is_reported_when_events_are_near_target(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    artifact_path = tmp_path / "runtime_post_signal.json"
    _write_db(db_path, [_payload("MEANREVERSION", "AVAXUSDTM", "buy", 10, 0.05)])
    _write_runtime_artifact(artifact_path, db_path, min_samples=20)

    report = analyze_post_signal_alpha_target_failure(artifact_path)

    assert report["classification"] == CLASS_SAMPLE_TOO_SMALL
    assert report["near_target_counts"]["25pct"] == 1
    assert report["summary"]["clean_event_count"] == 1
