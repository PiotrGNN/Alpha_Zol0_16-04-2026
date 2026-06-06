import json
import sqlite3

from scripts.immediate_adverse_shadow_reachability_gap import analyze_reachability_gap


def _log(db_path, event, payload):
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "create table if not exists logs (id integer primary key, timestamp text, event text, details text)"
        )
        connection.execute(
            "insert into logs(timestamp, event, details) values(datetime('now'), ?, ?)",
            (event, json.dumps(payload)),
        )


def test_analyze_reachability_gap_classifies_upstream_blocker(tmp_path):
    db_path = tmp_path / "run.db"
    _log(
        db_path,
        "entry_eval_v2",
        {
            "symbol": "SOLUSDTM",
            "strategy": "TrendFollowingV2",
            "side": "buy",
            "reason_code": "entry_edge_filtered",
            "final_allow": False,
        },
    )
    _log(
        db_path,
        "entry_gate_decision_summary",
        {"symbol": "SOLUSDTM", "local_gate_reason": "entry_edge_filtered"},
    )
    _log(
        db_path,
        "runtime_v2_stopped",
        {
            "risk_candidate_seen_count": 0,
            "shadow_candidate_registered_count": 0,
            "shadow_terminal_outcome_count": 0,
            "shadow_registration_skipped_count": 0,
            "shadow_registration_skip_reason_distribution": {},
        },
    )

    report = analyze_reachability_gap(db_path=db_path, report_json_path=None)

    assert report["funnel"]["strategy_candidates_produced"] == 1
    assert report["funnel"]["risk_candidate_seen_count"] == 0
    assert report["top_blocker_before_risk_engine"] == "entry_edge_filtered"
    assert report["solusdtm_buy_trendfollowing_seen"] is True
    assert report["classification"] == "SHADOW_REACHABILITY_BLOCKED_UPSTREAM"
