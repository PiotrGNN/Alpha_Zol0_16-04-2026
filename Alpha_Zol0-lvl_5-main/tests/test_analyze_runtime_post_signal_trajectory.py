import json
import sqlite3
from pathlib import Path

from scripts.analyze_runtime_post_signal_trajectory import analyze_db_paths


def _init_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event TEXT NOT NULL,
            details TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def _insert(path: Path, payload: dict) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO logs(timestamp, event, details) VALUES(?, ?, ?)",
        ("2026-06-04T00:00:00Z", "post_signal_trajectory_v2", json.dumps(payload)),
    )
    conn.commit()
    conn.close()


def _payload(
    *,
    strategy: str = "MomentumV2",
    signed_net_move: float = 0.13,
    contaminated: bool = False,
) -> dict:
    return {
        "symbol": "BTCUSDTM",
        "strategy": strategy,
        "canonical_strategy": strategy.replace("V2", "").upper(),
        "side": "buy",
        "source": "rolling_quote_window",
        "runtime_profile_key": "BTCUSDTM|rolling_quote_window|n=64|span=300",
        "horizon_ticks": 3,
        "signed_net_move": signed_net_move,
        "signed_gross_move": signed_net_move + 0.0004,
        "estimated_cost": 0.0004,
        "contamination_flags": {
            "seed": 0,
            "fallback": int(contaminated),
            "mock": 0,
            "force_open": 0,
            "forced_cycle": 0,
        },
    }


def test_analyzer_classifies_missing_rows_as_telemetry_gap(tmp_path: Path):
    db_path = tmp_path / "empty.db"
    _init_db(db_path)

    report = analyze_db_paths([db_path])

    assert report["classification"] == "POST_SIGNAL_TRAJECTORY_BLOCKED_BY_TELEMETRY_GAP"
    assert report["summary"]["trajectory_event_count"] == 0


def test_analyzer_classifies_contaminated_rows(tmp_path: Path):
    db_path = tmp_path / "contaminated.db"
    _init_db(db_path)
    _insert(db_path, _payload(contaminated=True))

    report = analyze_db_paths([db_path])

    assert report["classification"] == "POST_SIGNAL_TRAJECTORY_EVIDENCE_CONTAMINATED"
    assert report["summary"]["clean_event_count"] == 0


def test_analyzer_ranks_clean_non_trend_targets_and_keeps_trend_baseline(tmp_path: Path):
    db_path = tmp_path / "trajectory.db"
    _init_db(db_path)
    for _ in range(20):
        _insert(db_path, _payload(strategy="MomentumV2", signed_net_move=0.13))
    for _ in range(20):
        _insert(db_path, _payload(strategy="TrendFollowingV2", signed_net_move=0.20))

    report = analyze_db_paths([db_path], min_samples=20, min_p95_signed_net=0.12)

    assert report["classification"] == "POST_SIGNAL_TRAJECTORY_ALPHA_TARGETS_FOUND"
    assert report["summary"]["alpha_target_count"] == 1
    assert report["alpha_targets"][0]["canonical_strategy"] == "MOMENTUM"
    assert report["baseline_candidates"][0]["canonical_strategy"] == "TRENDFOLLOWING"
