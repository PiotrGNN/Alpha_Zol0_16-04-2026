import json
import sqlite3
import sys
from pathlib import Path

import scripts.report_entry_gate_decision_summary as summary_module

from scripts.report_entry_gate_decision_summary import build_report


def _payload(symbol="ETHUSDTM", side="buy", final_allow=False):
    return {
        "ts": "2026-03-27T00:00:00+00:00",
        "symbol": symbol,
        "side": side,
        "final_allow": final_allow,
        "entry_gate_bucket": "economics_or_quality_guard",
        "global_block_reason": "edge_over_fee_gate",
        "local_gate_reason": "edge_over_fee_gate",
        "effective_gate_reason": "edge_over_fee_gate",
        "effective_gate_reason_origin": "local_gate_reason",
        "paper_gate_active": False,
        "paper_gate_reason": None,
        "paper_gate_mode": None,
        "risk_allow_before_paper_gate": False,
        "paper_gate_override": False,
        "entry_decision_raw": "buy",
        "entry_decision_final": "buy",
        "entry_reason": "edge_over_fee_gate",
        "entry_reason_classification": "risk_block",
        "entry_live_edge": {"pass": True},
        "entry_edge_over_fee": {
            "blocked": False,
            "history_ready": True,
            "reason": "allow_edge_over_threshold",
        },
        "entry_edge_after_execution": {"edge_after_execution": 0.001},
        "spread": {"abs": 0.0, "pct": 0.0, "bps": 0.0},
        "liquidity_ok": True,
        "confidence": 0.99,
        "fee_estimate": 0.001,
        "current_edge": 0.002,
        "realtime_edge": 0.002,
        "max_positions_blocked": False,
    }


def _risk_payload(symbol="ETHUSDTM"):
    return {
        "symbol": symbol,
        "entry_decision": "buy",
        "allow": True,
    }


def _position_open_payload(
    symbol="ETHUSDTM",
    *,
    side="buy",
    entry_main_strategy="TrendFollowing",
    entry_reason="paper_auto_open_allowlisted",
    decision_router_path="paper_auto_open_allowlisted",
    override_reason="paper_auto_open_allowlisted",
    selection_source="entry_symbol_strategy_side_allowlist",
    truth="BOOTSTRAP_ALLOWLIST_ASSISTED",
    canonical_bucket=None,
):
    if canonical_bucket is None:
        canonical_bucket = {
            "canonical_bucket_key": f"{symbol}|{entry_main_strategy.upper()}|{side}",
            "bucket_identity_status": "RESOLVED",
            "bucket_identity_reason": "explicit_strategy",
            "symbol": symbol,
            "side": side,
            "strategy_identity": entry_main_strategy.upper(),
            "raw_symbol": symbol,
            "raw_strategy": entry_main_strategy,
            "raw_side": side,
            "normalized_symbol": symbol,
            "normalized_strategy": entry_main_strategy.upper(),
            "normalized_side": side,
            "strategy_source": "strategy",
        }
    return {
        "symbol": symbol,
        "side": side,
        "strategy": entry_main_strategy,
        "entry_main_strategy": entry_main_strategy,
        "canonical_bucket": canonical_bucket,
        "canonical_bucket_key": canonical_bucket["canonical_bucket_key"],
        "trade_id": f"{symbol}-trade-1",
        "entry_reason": entry_reason,
        "decision_router_path": decision_router_path,
        "override_reason": override_reason,
        "selection_source": selection_source,
        "entry_open_truth_classification": truth,
    }


def _init_db(db_path: Path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("create table logs (timestamp text, event text, details text)")
    conn.commit()
    conn.close()


def _insert(db_path: Path, event: str, payload: dict):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "insert into logs (timestamp, event, details) values (?, ?, ?)",
        ("2026-03-27 00:00:00", event, json.dumps(payload)),
    )
    conn.commit()
    conn.close()


def test_build_report_accepts_one_trailing_summary(tmp_path):
    db_path = tmp_path / "test.db"
    _init_db(db_path)
    _insert(db_path, "entry_gate_decision_summary", _payload(symbol="ETHUSDTM"))
    _insert(db_path, "risk_decision", _risk_payload(symbol="ETHUSDTM"))
    _insert(db_path, "entry_gate_decision_summary", _payload(symbol="BTCUSDTM"))

    report = build_report(db_path, hours=None)

    assert report["rows"] == 2
    assert report["risk_decision_rows"] == 1
    assert report["count_alignment"]["count_matches"] is True
    assert report["ordering"]["all_pairs_in_order"] is True
    assert report["ordering"]["trailing_summary_rows"] == 1
    assert report["payload_completeness"]["all_complete"] is True


def test_build_report_baseline_pairing_still_works(tmp_path):
    db_path = tmp_path / "test2.db"
    _init_db(db_path)
    _insert(db_path, "entry_gate_decision_summary", _payload(symbol="ETHUSDTM"))
    _insert(db_path, "risk_decision", _risk_payload(symbol="ETHUSDTM"))

    report = build_report(db_path, hours=None)

    assert report["rows"] == 1
    assert report["risk_decision_rows"] == 1
    assert report["count_alignment"]["count_matches"] is True
    assert report["ordering"]["all_pairs_in_order"] is True
    assert report["ordering"]["trailing_summary_rows"] == 0


def test_build_report_counts_position_open_truth_classification(tmp_path):
    db_path = tmp_path / "open_truth.db"
    _init_db(db_path)
    _insert(db_path, "position_open", _position_open_payload())
    _insert(db_path, "entry_gate_decision_summary", _payload(symbol="ETHUSDTM"))
    _insert(db_path, "risk_decision", _risk_payload(symbol="ETHUSDTM"))

    report = build_report(db_path, hours=None)

    assert report["position_open_rows"] == 1
    assert report["position_open_truth_classification_counts"] == [
        ("BOOTSTRAP_ALLOWLIST_ASSISTED", 1)
    ]
    assert (
        report["last_position_open"]["entry_open_truth_classification"]
        == "BOOTSTRAP_ALLOWLIST_ASSISTED"
    )
    assert report["last_position_open"]["side"] == "buy"
    assert report["last_position_open"]["entry_main_strategy"] == "TrendFollowing"
    assert report["last_position_open"]["canonical_bucket_key"] == (
        "ETHUSDTM|TRENDFOLLOWING|buy"
    )


def test_build_report_inferrs_position_open_truth_when_field_missing(tmp_path):
    db_path = tmp_path / "open_truth_fallback.db"
    _init_db(db_path)
    payload = _position_open_payload()
    payload.pop("entry_open_truth_classification")
    _insert(db_path, "position_open", payload)
    _insert(db_path, "entry_gate_decision_summary", _payload(symbol="ETHUSDTM"))
    _insert(db_path, "risk_decision", _risk_payload(symbol="ETHUSDTM"))

    report = build_report(db_path, hours=None)

    assert report["position_open_rows"] == 1
    assert report["position_open_truth_classification_counts"] == [
        ("BOOTSTRAP_ALLOWLIST_ASSISTED", 1)
    ]
    assert (
        report["last_position_open"]["entry_open_truth_classification"]
        == "BOOTSTRAP_ALLOWLIST_ASSISTED"
    )
    assert report["last_position_open"]["side"] == "buy"
    assert report["last_position_open"]["canonical_bucket_key"] == (
        "ETHUSDTM|TRENDFOLLOWING|buy"
    )


def test_main_prints_report_json_for_cli_invocation(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "cli.db"
    _init_db(db_path)
    _insert(db_path, "entry_gate_decision_summary", _payload(symbol="ETHUSDTM"))
    _insert(db_path, "risk_decision", _risk_payload(symbol="ETHUSDTM"))

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "report_entry_gate_decision_summary.py",
            "--db-path",
            str(db_path),
            "--hours",
            "0",
        ],
    )

    summary_module.main()
    output = capsys.readouterr().out
    report = json.loads(output)

    assert report["rows"] == 1
    assert report["risk_decision_rows"] == 1
    assert report["count_alignment"]["count_matches"] is True
    assert report["ordering"]["all_pairs_in_order"] is True
