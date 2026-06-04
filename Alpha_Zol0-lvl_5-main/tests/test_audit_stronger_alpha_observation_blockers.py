from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.audit_stronger_alpha_observation_blockers import (
    CLASS_CONTAMINATED,
    CLASS_ENTRY_EDGE_FILTER_DOMINANT,
    CLASS_NO_POSITION_OPEN,
    audit_observation_blockers,
)


def _write_targets(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "classification": "STRONGER_ALPHA_OBSERVATION_TARGETS_SELECTED",
                "selected_targets": [
                    {"candidate_key": "BTCUSDTM:MOMENTUM:sell"},
                    {"candidate_key": "BNBUSDTM:MEANREVERSION:sell"},
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_db(path: Path, rows: list[tuple[str, dict]]) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE logs (timestamp TEXT, event TEXT, details TEXT)")
        conn.execute("CREATE TABLE decisions (timestamp TEXT, decision TEXT, details TEXT)")
        for idx, (event, payload) in enumerate(rows):
            conn.execute(
                "INSERT INTO logs (timestamp, event, details) VALUES (?, ?, ?)",
                (f"2026-06-04T00:00:{idx:02d}", event, json.dumps(payload)),
            )
            if event in {"entry_reject_v2", "entry_eval_v2"}:
                conn.execute(
                    "INSERT INTO decisions (timestamp, decision, details) VALUES (?, ?, ?)",
                    (f"2026-06-04T00:00:{idx:02d}", "hold", json.dumps(payload)),
                )
        conn.commit()
    finally:
        conn.close()


def _event(symbol: str, strategy: str, side: str, reason: str, *, contaminated: bool = False) -> dict:
    return {
        "symbol": symbol,
        "canonical_strategy": strategy,
        "strategy": strategy.title(),
        "side": side,
        "reason_code": reason,
        "source": "rolling_quote_window",
        "contamination_flags": {
            "seed": int(contaminated),
            "fallback": 0,
            "mock": 0,
            "force_open": 0,
            "forced_cycle": 0,
        },
    }


def test_classifies_targeted_zero_trade_run_as_entry_edge_filter_dominant(tmp_path: Path) -> None:
    db_path = tmp_path / "run.db"
    targets_path = tmp_path / "targets.json"
    _write_targets(targets_path)
    _write_db(
        db_path,
        [
            ("entry_reject_v2", {"symbol": "SOLUSDTM", "reason_code": "symbol_strategy_side_allowlist"}),
            ("entry_eval_v2", _event("BTCUSDTM", "MOMENTUM", "sell", "entry_edge_filtered")),
            ("post_signal_trajectory_v2", _event("BTCUSDTM", "MOMENTUM", "sell", "entry_edge_filtered")),
            ("post_signal_trajectory_v2", _event("BNBUSDTM", "MEANREVERSION", "sell", "entry_edge_filtered")),
        ],
    )

    report = audit_observation_blockers(db_path, targets_path)

    assert report["classification"] == CLASS_ENTRY_EDGE_FILTER_DOMINANT
    assert report["summary"]["position_open_count"] == 0
    assert report["target_reason_counts"]["entry_edge_filtered"] == 3
    assert report["global_reason_counts"]["symbol_strategy_side_allowlist"] == 1


def test_classifies_no_position_open_when_no_target_rejections_exist(tmp_path: Path) -> None:
    db_path = tmp_path / "run.db"
    targets_path = tmp_path / "targets.json"
    _write_targets(targets_path)
    _write_db(db_path, [("entry_reject_v2", {"symbol": "SOLUSDTM", "reason_code": "no_runtime_profile"})])

    report = audit_observation_blockers(db_path, targets_path)

    assert report["classification"] == CLASS_NO_POSITION_OPEN
    assert report["target_reason_counts"] == {}


def test_contamination_overrides_blocker_classification(tmp_path: Path) -> None:
    db_path = tmp_path / "run.db"
    targets_path = tmp_path / "targets.json"
    _write_targets(targets_path)
    _write_db(
        db_path,
        [
            ("post_signal_trajectory_v2", _event("BTCUSDTM", "MOMENTUM", "sell", "entry_edge_filtered", contaminated=True)),
        ],
    )

    report = audit_observation_blockers(db_path, targets_path)

    assert report["classification"] == CLASS_CONTAMINATED
    assert report["summary"]["contaminated_event_count"] == 1
