import json
import sqlite3
from pathlib import Path

import pytest

from scripts.discover_runtime_compatible_alpha_candidates import (
    canonical_strategy,
    discover,
    scan_runtime_db,
)


def _init_logs_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME NOT NULL,
            event VARCHAR(64) NOT NULL,
            details TEXT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def _insert_log(path: Path, event: str, payload: dict) -> None:
    conn = sqlite3.connect(str(path))
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO logs(timestamp, event, details) VALUES(?, ?, ?)",
        ("2026-06-04T01:00:00Z", event, json.dumps(payload)),
    )
    conn.commit()
    conn.close()


def _runtime_payload(**overrides):
    payload = {
        "symbol": "BNBUSDTM",
        "strategy": "TrendFollowingV2",
        "side": "buy",
        "reason_code": "entry_min_net_guard",
        "runtime_profile_source": "rolling_quote_window",
        "runtime_profile_key": "BNBUSDTM|rolling_quote_window|n=180|span=900",
        "runtime_profile_age_sec": 120.0,
        "runtime_profile_span_sec": 900.0,
        "runtime_profile_sample_size": 180,
        "cost_breakdown": {
            "fee_rate": 0.0001,
            "spread_ratio": 0.00002,
            "slippage_ratio": 0.00005,
        },
        "risk_block_fields": {
            "sizing_trace": {
                "expected_net_after_full_cost": 0.14,
                "entry_min_net_usdt": 0.12,
            }
        },
    }
    payload.update(overrides)
    return payload


def test_canonical_strategy_normalizes_runtime_aliases() -> None:
    assert canonical_strategy("TrendFollowingV2") == "TRENDFOLLOWING"
    assert canonical_strategy("trend_following") == "TRENDFOLLOWING"
    assert canonical_strategy("MicroBreakoutV2") == "MICROBREAKOUT"


def test_scan_runtime_db_promotes_only_current_source_threshold_clean_candidate(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    _init_logs_db(db_path)
    _insert_log(db_path, "entry_reject_v2", _runtime_payload())

    result = scan_runtime_db(db_path, min_expected_net_usdt=0.12)

    assert result["record_count"] == 1
    candidate = result["candidates"][0]
    assert candidate["candidate_key"] == "BNBUSDTM:TRENDFOLLOWING:buy"
    assert candidate["source"] == "rolling_quote_window"
    assert candidate["source_parity_status"] == "SOURCE_PARITY_PROVEN"
    assert candidate["expected_net_after_full_cost"] == 0.14
    assert candidate["effective_entry_min_net_usdt"] == 0.12
    assert candidate["clears_threshold"] is True
    assert candidate["runtime_profile_exists"] is True
    assert candidate["source_parity_proven"] is True
    assert candidate["runtime_admissible"] is True
    assert (
        candidate["runtime_admissibility_classification"]
        == "RUNTIME_COMPATIBLE_CANDIDATE_FOUND"
    )


def test_discover_fails_closed_when_edge_is_below_threshold(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _init_logs_db(db_path)
    _insert_log(
        db_path,
        "entry_reject_v2",
        _runtime_payload(
            risk_block_fields={
                "sizing_trace": {
                    "expected_net_after_full_cost": 0.08,
                    "entry_min_net_usdt": 0.12,
                }
            }
        ),
    )

    report = discover([db_path], min_expected_net_usdt=0.12)

    assert report["summary"]["classification"] == "NO_RUNTIME_COMPATIBLE_CANDIDATE_FOUND"
    candidate = report["candidates"][0]
    assert candidate["runtime_admissible"] is False
    assert (
        candidate["runtime_admissibility_classification"]
        == "NOT_RUNTIME_ADMISSIBLE_EDGE_BELOW_THRESHOLD"
    )


def test_discover_blocks_when_profile_data_is_missing(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _init_logs_db(db_path)
    _insert_log(db_path, "entry_reject_v2", _runtime_payload(runtime_profile_key=None))

    report = discover([db_path], min_expected_net_usdt=0.12)

    assert (
        report["summary"]["classification"]
        == "RUNTIME_COMPATIBLE_DISCOVERY_BLOCKED_BY_MISSING_PROFILE_DATA"
    )
    assert (
        report["candidates"][0]["runtime_admissibility_classification"]
        == "NOT_RUNTIME_ADMISSIBLE_PROFILE_MISSING"
    )


def test_discover_fails_closed_when_profile_is_stale(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _init_logs_db(db_path)
    _insert_log(db_path, "entry_reject_v2", _runtime_payload(runtime_profile_age_sec=600.0))

    report = discover([db_path], min_expected_net_usdt=0.12, max_profile_age_sec=300.0)

    assert report["summary"]["classification"] == "NO_RUNTIME_COMPATIBLE_CANDIDATE_FOUND"
    assert (
        report["candidates"][0]["runtime_admissibility_classification"]
        == "NOT_RUNTIME_ADMISSIBLE_STALE_PROFILE"
    )


def test_discover_fails_closed_on_non_runtime_source(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _init_logs_db(db_path)
    _insert_log(
        db_path,
        "entry_reject_v2",
        _runtime_payload(runtime_profile_source="kucoin_public_futures_klines"),
    )

    report = discover([db_path], min_expected_net_usdt=0.12)

    assert report["summary"]["classification"] == "NO_RUNTIME_COMPATIBLE_CANDIDATE_FOUND"
    assert (
        report["candidates"][0]["runtime_admissibility_classification"]
        == "NOT_RUNTIME_ADMISSIBLE_SOURCE_MISMATCH"
    )


def test_discover_blocks_when_required_edge_telemetry_is_missing(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    _init_logs_db(db_path)
    _insert_log(
        db_path,
        "entry_reject_v2",
        _runtime_payload(risk_block_fields={"sizing_trace": {"entry_min_net_usdt": 0.12}}),
    )

    report = discover([db_path], min_expected_net_usdt=0.12)

    assert (
        report["summary"]["classification"]
        == "RUNTIME_COMPATIBLE_DISCOVERY_BLOCKED_BY_TELEMETRY_GAP"
    )
    assert (
        report["candidates"][0]["runtime_admissibility_classification"]
        == "NOT_RUNTIME_ADMISSIBLE_TELEMETRY_GAP"
    )


def test_false_contamination_flags_do_not_block_clean_runtime_evidence(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    _init_logs_db(db_path)
    _insert_log(
        db_path,
        "entry_reject_v2",
        _runtime_payload(use_mock=False, fallback=False, seeded=False, forced_cycle=False),
    )

    report = discover([db_path], min_expected_net_usdt=0.12)

    assert report["summary"]["classification"] == "RUNTIME_COMPATIBLE_CANDIDATE_FOUND"
    assert report["summary"]["contamination_counts"]["mock"] == 0
    assert report["summary"]["contamination_counts"]["fallback"] == 0
