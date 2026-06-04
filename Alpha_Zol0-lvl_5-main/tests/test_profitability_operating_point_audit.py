from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.profitability_operating_point_audit import (
    CLASS_CANDIDATE_FOUND,
    CLASS_CONTAMINATED,
    CLASS_COST_DOMINATED,
    CLASS_NO_OPERATING_POINT,
    audit_operating_point,
)


def _write_runtime_artifact(path: Path, db_path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "classification": "POST_SIGNAL_TRAJECTORY_NO_TARGETS",
                "inputs": {"db_paths": [str(db_path)]},
                "summary": {"trajectory_event_count": 0, "clean_event_count": 0, "contaminated_event_count": 0},
            }
        ),
        encoding="utf-8",
    )


def _write_blocker_artifact(path: Path, classification: str = "STRONGER_ALPHA_OBSERVATION_BLOCKED_BY_ENTRY_EDGE_FILTER") -> None:
    path.write_text(
        json.dumps(
            {
                "classification": classification,
                "summary": {"position_open_count": 0},
                "target_reason_counts": {"entry_edge_filtered": 10},
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
                (f"2026-06-04T00:{idx // 60:02d}:{idx % 60:02d}", "post_signal_trajectory_v2", json.dumps(payload)),
            )
        conn.commit()
    finally:
        conn.close()


def _payload(
    symbol: str,
    strategy: str,
    side: str,
    horizon: int,
    net: float,
    *,
    gross: float | None = None,
    cost: float = 0.00025,
    contaminated: bool = False,
) -> dict:
    gross_value = gross if gross is not None else net + cost
    return {
        "symbol": symbol,
        "canonical_strategy": strategy,
        "strategy": strategy,
        "side": side,
        "source": "rolling_quote_window",
        "horizon_ticks": horizon,
        "signed_gross_move": gross_value,
        "estimated_cost": cost,
        "signed_net_move": net,
        "expected_net_after_cost": net / 2,
        "contamination_flags": {"seed": int(contaminated), "fallback": 0, "mock": 0, "force_open": 0, "forced_cycle": 0},
    }


def test_finds_operating_point_when_frequency_winrate_and_payoff_pass(tmp_path: Path) -> None:
    db_path = tmp_path / "run.db"
    runtime_path = tmp_path / "runtime.json"
    blocker_path = tmp_path / "blockers.json"
    payloads = [_payload("BTCUSDTM", "MOMENTUM", "sell", 10, 0.002) for _ in range(16)]
    payloads += [_payload("BTCUSDTM", "MOMENTUM", "sell", 10, -0.0008, gross=-0.00055) for _ in range(4)]
    _write_db(db_path, payloads)
    _write_runtime_artifact(runtime_path, db_path)
    _write_blocker_artifact(blocker_path)

    report = audit_operating_point(runtime_path, blocker_path)

    assert report["classification"] == CLASS_CANDIDATE_FOUND
    assert report["best_operating_point"]["candidate_key"] == "BTCUSDTM:MOMENTUM:sell:h10"
    assert report["best_operating_point"]["win_rate"] == 0.8
    assert report["profitability_claim"] is False


def test_classifies_cost_dominated_when_gross_opportunity_is_smaller_than_cost(tmp_path: Path) -> None:
    db_path = tmp_path / "run.db"
    runtime_path = tmp_path / "runtime.json"
    blocker_path = tmp_path / "blockers.json"
    payloads = [_payload("SOLUSDTM", "MOMENTUM", "sell", 5, -0.0001, gross=0.0001, cost=0.0002) for _ in range(20)]
    _write_db(db_path, payloads)
    _write_runtime_artifact(runtime_path, db_path)
    _write_blocker_artifact(blocker_path)

    report = audit_operating_point(runtime_path, blocker_path)

    assert report["classification"] == CLASS_COST_DOMINATED
    assert report["best_operating_point"] is None


def test_contamination_overrides_operating_point(tmp_path: Path) -> None:
    db_path = tmp_path / "run.db"
    runtime_path = tmp_path / "runtime.json"
    blocker_path = tmp_path / "blockers.json"
    _write_db(db_path, [_payload("BTCUSDTM", "MOMENTUM", "sell", 10, 0.002, contaminated=True)])
    _write_runtime_artifact(runtime_path, db_path)
    _write_blocker_artifact(blocker_path)

    report = audit_operating_point(runtime_path, blocker_path)

    assert report["classification"] == CLASS_CONTAMINATED
    assert report["summary"]["contaminated_event_count"] == 1


def test_no_operating_point_when_winrate_and_payoff_fail(tmp_path: Path) -> None:
    db_path = tmp_path / "run.db"
    runtime_path = tmp_path / "runtime.json"
    blocker_path = tmp_path / "blockers.json"
    payloads = [_payload("XRPUSDTM", "MOMENTUM", "sell", 3, 0.0003) for _ in range(8)]
    payloads += [_payload("XRPUSDTM", "MOMENTUM", "sell", 3, -0.001) for _ in range(12)]
    _write_db(db_path, payloads)
    _write_runtime_artifact(runtime_path, db_path)
    _write_blocker_artifact(blocker_path)

    report = audit_operating_point(runtime_path, blocker_path)

    assert report["classification"] == CLASS_NO_OPERATING_POINT
    assert report["best_operating_point"] is None


def test_insufficient_sample_is_not_cost_dominated(tmp_path: Path) -> None:
    db_path = tmp_path / "run.db"
    runtime_path = tmp_path / "runtime.json"
    blocker_path = tmp_path / "blockers.json"
    payloads = [_payload("BTCUSDTM", "MEANREVERSION", "sell", 10, 0.002) for _ in range(11)]
    _write_db(db_path, payloads)
    _write_runtime_artifact(runtime_path, db_path)
    _write_blocker_artifact(blocker_path)

    report = audit_operating_point(runtime_path, blocker_path)

    assert report["classification"] == CLASS_NO_OPERATING_POINT
    assert report["summary"]["passing_bucket_count"] == 0
