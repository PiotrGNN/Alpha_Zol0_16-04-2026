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
    payload = {
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
    }
    if truth is not None:
        payload["entry_open_truth_classification"] = truth
    return payload


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


def test_build_report_marks_no_router_candidates_as_unusable_strategy_evidence(
    tmp_path,
):
    db_path = tmp_path / "no_router_candidates.db"
    _init_db(db_path)
    _insert(db_path, "entry_gate_decision_summary", _payload(symbol="ETHUSDTM"))
    _insert(db_path, "risk_decision", _risk_payload(symbol="ETHUSDTM"))

    report = build_report(db_path, hours=None)
    contract = report["natural_entry_candidate_contract"]

    assert contract["classification"] == "NO_ROUTER_CANDIDATES_OBSERVED"
    assert contract["usable_strategy_economics"] is False
    assert (
        contract["strategy_evidence_classification"]
        == "NO_ROUTER_CANDIDATES_OBSERVED"
    )
    assert "NO_ROUTER_CANDIDATES_OBSERVED" in contract["reason_codes"]


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


def test_build_report_marks_seed_trade_open_as_assisted_evidence(tmp_path):
    db_path = tmp_path / "seed_assisted.db"
    _init_db(db_path)
    gate_payload = _payload(symbol="BTCUSDTM", side="sell", final_allow=True)
    gate_payload.update(
        {
            "entry_decision_raw": "sell",
            "entry_decision_final": "sell",
            "entry_reason": "seed_trades_override",
            "main_strategy": "Momentum",
            "natural_path_trace": {
                "pre_entry_candidate_exists": True,
                "strategy_assignment_stage": "router_assignment",
                "main_strategy": "Momentum",
                "side": "sell",
            },
        }
    )
    _insert(db_path, "entry_gate_decision_summary", gate_payload)
    _insert(db_path, "risk_decision", _risk_payload(symbol="BTCUSDTM"))
    _insert(
        db_path,
        "position_open",
        _position_open_payload(
            symbol="BTCUSDTM",
            side="sell",
            entry_main_strategy="Momentum",
            entry_reason="seed_trades_override",
            decision_router_path="router_selection",
            override_reason=None,
            selection_source=None,
            truth=None,
        ),
    )

    report = build_report(db_path, hours=None)
    contract = report["natural_entry_candidate_contract"]

    assert report["position_open_truth_classification_counts"] == [
        ("SEED_TRADES_OVERRIDE_ASSISTED", 1)
    ]
    assert (
        report["last_position_open"]["entry_open_truth_classification"]
        == "SEED_TRADES_OVERRIDE_ASSISTED"
    )
    assert contract["classification"] == "NATURAL_ENTRY_CANDIDATE_PRESENT"
    assert contract["natural_admitted_count"] == 0
    assert contract["assisted_seed_admitted_count"] == 1
    assert contract["assisted_seed_open_count"] == 1
    assert contract["assisted_seed_evidence_only"] is True
    assert contract["usable_strategy_economics"] is False
    assert contract["strategy_evidence_classification"] == "ASSISTED_SEED_EVIDENCE_ONLY"
    assert contract["assisted_seed_allowed_sides"] == [
        {
            "symbol": "BTCUSDTM",
            "strategy": "Momentum",
            "side": "sell",
            "count": 1,
        }
    ]


def test_build_report_classifies_decision_passed_open_as_natural_entry(tmp_path):
    db_path = tmp_path / "natural_open_truth.db"
    _init_db(db_path)
    gate_payload = _payload(symbol="ETHUSDTM", side="buy", final_allow=True)
    gate_payload.update(
        {
            "entry_decision_raw": "buy",
            "entry_decision_final": "buy",
            "entry_reason": "decision_passed",
            "main_strategy": "Momentum",
            "natural_path_trace": {
                "pre_entry_candidate_exists": True,
                "strategy_assignment_stage": "router_selection",
                "strategy_candidate": "Momentum",
                "side_candidate": "buy",
            },
        }
    )
    open_payload = _position_open_payload(
        symbol="ETHUSDTM",
        side="buy",
        entry_main_strategy="Momentum",
        entry_reason="decision_passed",
        decision_router_path="Momentum",
        override_reason="none",
        selection_source=None,
        truth=None,
    )
    open_payload.pop("entry_open_truth_classification", None)
    _insert(db_path, "entry_gate_decision_summary", gate_payload)
    _insert(db_path, "risk_decision", _risk_payload(symbol="ETHUSDTM"))
    _insert(db_path, "position_open", open_payload)

    report = build_report(db_path, hours=None)

    assert report["position_open_truth_classification_counts"] == [
        ("NATURAL_STRATEGY_ENTRY", 1)
    ]
    assert (
        report["last_position_open"]["entry_open_truth_classification"]
        == "NATURAL_STRATEGY_ENTRY"
    )
    assert (
        report["natural_entry_candidate_contract"]["strategy_evidence_classification"]
        == "USABLE_STRATEGY_EVIDENCE"
    )


def test_build_report_detects_filter_to_none_no_natural_candidate(tmp_path):
    db_path = tmp_path / "filter_to_none.db"
    _init_db(db_path)
    gate_payload = _payload(symbol="XRPUSDTM", side=None, final_allow=False)
    gate_payload.update(
        {
            "global_block_reason": "missing_strategy_field",
            "local_gate_reason": "missing_strategy_field",
            "effective_gate_reason": "missing_strategy_field",
            "entry_decision_raw": "hold",
            "entry_decision_final": "hold",
            "natural_path_trace": {
                "pre_entry_candidate_exists": True,
                "strategy_assignment_stage": "pre_entry_candidate_rejection",
                "short_circuit_stage": "pre_entry_candidate_rejection",
            },
            "main_strategy": None,
        }
    )
    _insert(
        db_path,
        "pre_entry_candidate_rejection_trace",
        {
            "symbol": "XRPUSDTM",
            "normalized_strategy_value": "Momentum",
            "normalized_side_value": "buy",
            "rejection_reason_code": "symbol_strategy_side_allowlist",
            "rejection_predicate_name": "_entry_prefilter_reason(strategy_name, side)",
            "rejection_stage": "pre_entry_candidate_rejection",
        },
    )
    _insert(
        db_path,
        "pre_entry_candidate_rejection_trace",
        {
            "symbol": "XRPUSDTM",
            "normalized_strategy_value": "TrendFollowing",
            "normalized_side_value": "buy",
            "rejection_reason_code": "symbol_strategy_guard",
            "rejection_predicate_name": "_symbol_strategy_guard_check",
            "rejection_stage": "pre_entry_candidate_rejection",
        },
    )
    _insert(
        db_path,
        "pre_entry_candidate_rejection_trace",
        {
            "symbol": "XRPUSDTM",
            "normalized_strategy_value": "MeanReversion",
            "normalized_side_value": None,
            "rejection_reason_code": "invalid_side",
            "rejection_predicate_name": "side in ('buy', 'sell', 'hold')",
            "rejection_stage": "pre_entry_candidate_rejection",
        },
    )
    _insert(db_path, "entry_gate_decision_summary", gate_payload)
    _insert(db_path, "risk_decision", _risk_payload(symbol="XRPUSDTM"))
    _insert(
        db_path,
        "position_open",
        _position_open_payload(
            symbol="XRPUSDTM",
            side="buy",
            entry_main_strategy="Momentum",
            entry_reason="auto_test_open",
            decision_router_path="paper_auto_open_fallback",
            override_reason="paper_auto_open_fallback",
            selection_source="paper_auto_open_fallback",
            truth="PAPER_AUTO_OPEN_FALLBACK",
        ),
    )

    report = build_report(db_path, hours=None)
    contract = report["natural_entry_candidate_contract"]

    assert contract["classification"] == "NO_NATURAL_ENTRY_CANDIDATE"
    assert contract["usable_strategy_economics"] is False
    assert contract["strategy_evidence_classification"] == (
        "FALLBACK_ECONOMICS_NOT_STRATEGY_EVIDENCE"
    )
    assert contract["router_candidate_rows"] == 1
    assert contract["empty_assignment_rows"] == 1
    assert contract["final_surviving_candidate_count"] == 0
    assert contract["natural_admitted_count"] == 0
    assert contract["assisted_seed_admitted_count"] == 0
    assert contract["assisted_seed_open_count"] == 0
    assert contract["assisted_seed_evidence_only"] is False
    assert {
        "symbol": "XRPUSDTM",
        "strategy": "Momentum",
        "side": "buy",
        "count": 1,
    } in contract["router_candidate_sides"]
    assert {
        "symbol": "XRPUSDTM",
        "strategy": "Momentum",
        "side": "buy",
        "reason": "symbol_strategy_side_allowlist",
        "count": 1,
    } in contract["blocked_sides"]
    assert {
        "symbol": "XRPUSDTM",
        "strategy": "TrendFollowing",
        "side": "buy",
        "reason": "symbol_strategy_guard",
        "count": 1,
    } in contract["guard_rejected_sides"]
    assert "FILTER_TO_NONE_BEFORE_ASSIGNMENT" in contract["reason_codes"]
    assert "FALLBACK_ECONOMICS_NOT_STRATEGY_EVIDENCE" in contract["reason_codes"]


def test_build_report_dumps_top_raw_side_values_for_rejections(tmp_path):
    db_path = tmp_path / "raw_side_values.db"
    _init_db(db_path)
    _insert(db_path, "entry_gate_decision_summary", _payload(symbol="XRPUSDTM"))
    _insert(db_path, "risk_decision", _risk_payload(symbol="XRPUSDTM"))
    for _ in range(3):
        _insert(
            db_path,
            "pre_entry_candidate_rejection_trace",
            {
                "symbol": "XRPUSDTM",
                "normalized_strategy_value": "MeanReversion",
                "normalized_side_value": "hold",
                "raw_side_candidates": [
                    {
                        "source": "signal.signals",
                        "raw_value": "signals:empty",
                        "normalized_value": "hold",
                    }
                ],
                "rejection_reason_code": "hold_ignored",
                "rejection_stage": "pre_entry_candidate_rejection",
            },
        )
    _insert(
        db_path,
        "pre_entry_candidate_rejection_trace",
        {
            "symbol": "XRPUSDTM",
            "normalized_strategy_value": "Momentum",
            "normalized_side_value": "buy",
            "raw_side_candidates": [
                {
                    "source": "signal",
                    "raw_value": "long",
                    "normalized_value": "buy",
                }
            ],
            "rejection_reason_code": "alpha_whitelist",
            "rejection_stage": "pre_entry_candidate_rejection",
        },
    )

    report = build_report(db_path, hours=None)
    contract = report["natural_entry_candidate_contract"]

    assert contract["raw_side_value_counts_top20"][:2] == [
        {"raw_side": "signals:empty", "count": 3},
        {"raw_side": "long", "count": 1},
    ]


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
