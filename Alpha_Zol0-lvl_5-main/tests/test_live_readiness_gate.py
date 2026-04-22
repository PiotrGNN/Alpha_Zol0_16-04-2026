import json
from pathlib import Path

import pytest

from security.live_guard import (
    enforce_live_ready,
    evaluate_live_readiness_contract,
    is_live_ready,
    write_live_readiness_snapshot,
)


def _ready_state() -> dict:
    return {
        "last_run": {
            "process_returncode": 0,
            "shutdown_classification": "close_flush_done_pending_positions_zero",
            "pending_positions": 0,
            "close_request_backlog": 0,
        },
        "data_validity": {
            "accepted_corpus_exists": True,
            "no_rejected_runs_in_active_dataset": True,
            "corpus_size_trades": 60,
        },
        "strategy_validation": {
            "usable_strategy_economics": True,
            "economic_go_no_go": "GO",
            "profitability_metrics": {
                "expectancy": 0.01,
                "winrate": 0.55,
                "profit_factor": 1.2,
                "green_to_red_share": 0.2,
            }
        },
        "critical_blockers": {
            "CLOSE_FINALIZATION_BROKEN": False,
            "LINKAGE_LAYER_NO_EFFECT": False,
            "TERMINAL_TIMING_CUTOFF_CONFIRMED": False,
        },
    }


def test_live_blocked_when_runtime_not_clean():
    state = _ready_state()
    state["last_run"]["process_returncode"] = 1

    evaluation = evaluate_live_readiness_contract(state)

    assert is_live_ready(state) is False
    assert evaluation["live_ready"] is False
    assert "process_returncode_nonzero" in evaluation["live_block_reason"]
    with pytest.raises(RuntimeError, match="LIVE_BLOCKED_NOT_READY"):
        enforce_live_ready(state)


def test_live_blocked_when_corpus_too_small():
    state = _ready_state()
    state["data_validity"]["corpus_size_trades"] = 59

    evaluation = evaluate_live_readiness_contract(state)

    assert is_live_ready(state) is False
    assert evaluation["live_ready"] is False
    assert "accepted_corpus_below_min_trades" in evaluation["live_block_reason"]
    with pytest.raises(RuntimeError, match="LIVE_BLOCKED_NOT_READY"):
        enforce_live_ready(state)


def test_live_blocked_when_close_drain_failed():
    state = _ready_state()
    state["last_run"]["pending_positions"] = 1
    state["last_run"]["close_request_backlog"] = 1

    evaluation = evaluate_live_readiness_contract(state)

    assert is_live_ready(state) is False
    assert evaluation["live_ready"] is False
    assert "pending_positions_nonzero" in evaluation["live_block_reason"]
    assert "close_request_backlog_nonzero" in evaluation["live_block_reason"]
    with pytest.raises(RuntimeError, match="LIVE_BLOCKED_NOT_READY"):
        enforce_live_ready(state)


def test_live_blocked_when_strategy_economics_not_usable():
    state = _ready_state()
    state["strategy_validation"]["usable_strategy_economics"] = False
    state["strategy_validation"]["strategy_evidence_classification"] = (
        "ASSISTED_ENTRY_EVIDENCE_ONLY"
    )

    evaluation = evaluate_live_readiness_contract(state)

    assert is_live_ready(state) is False
    assert evaluation["live_ready"] is False
    assert "strategy_economics_not_usable" in evaluation["live_block_reason"]
    assert "strategy_evidence_not_usable:ASSISTED_ENTRY_EVIDENCE_ONLY" in evaluation[
        "live_block_reason"
    ]


def test_live_blocked_when_economic_channel_no_go():
    state = _ready_state()
    state["strategy_validation"]["economic_go_no_go"] = "NO-GO"

    evaluation = evaluate_live_readiness_contract(state)

    assert is_live_ready(state) is False
    assert evaluation["live_ready"] is False
    assert "economic_go_no_go_not_go" in evaluation["live_block_reason"]


def test_live_allowed_when_all_conditions_met(tmp_path: Path):
    state = _ready_state()
    snapshot_path = tmp_path / "live_readiness_snapshot.json"

    evaluation = enforce_live_ready(state)
    write_live_readiness_snapshot(evaluation, snapshot_path)
    persisted = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert is_live_ready(state) is True
    assert evaluation["live_ready"] is True
    assert evaluation["live_block_reason"] == []
    assert persisted["live_ready"] is True
    assert persisted["live_block_reason"] == []
