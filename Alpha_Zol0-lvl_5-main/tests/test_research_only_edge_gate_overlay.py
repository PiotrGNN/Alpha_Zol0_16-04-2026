import pytest

from core.BotCore import (
    _SEED_TRADES_ADMISSION_COUNT_BY_BUCKET,
    _apply_seed_trade_override,
    _research_only_edge_gate_debug,
    _research_only_edge_gate_overlay,
    _research_only_expected_edge_debug,
    _research_only_hold_transition_debug,
    _research_only_net_target_guard_debug,
    _seed_trade_history_count_for_override,
    _research_only_tf_gate_debug,
)


def test_edge_gate_default_off(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.delenv("RESEARCH_EDGE_GATE_EXPERIMENT_ENABLE", raising=False)
    monkeypatch.delenv("RESEARCH_EDGE_GATE_MARGIN_SHIFT", raising=False)
    monkeypatch.delenv("RESEARCH_EDGE_GATE_FEE_RELAX_BPS", raising=False)
    out = _research_only_edge_gate_overlay(
        0.001,
        0.0008,
        0.003,
        0.002,
        0.0025,
        True,
    )
    assert out[0] == 0.001
    assert out[1] is None
    assert out[2] is None
    assert out[3] is None


def test_edge_gate_live_noop(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("RESEARCH_EDGE_GATE_EXPERIMENT_ENABLE", "1")
    monkeypatch.setenv("RESEARCH_EDGE_GATE_MARGIN_SHIFT", "0.001")
    out = _research_only_edge_gate_overlay(
        0.001,
        0.0008,
        0.003,
        0.002,
        0.0025,
        True,
    )
    assert out[0] == 0.001
    assert out[1] is None
    assert out[2] is None


def test_edge_gate_margin_shift_changes_only_edge_gate_path(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("RESEARCH_EDGE_GATE_EXPERIMENT_ENABLE", "1")
    monkeypatch.setenv("RESEARCH_EDGE_GATE_MARGIN_SHIFT", "0.0005")
    out = _research_only_edge_gate_overlay(
        0.001,
        0.0008,
        0.003,
        0.002,
        0.0025,
        True,
    )
    assert out[0] == pytest.approx(0.0015)
    assert out[1] == "research_edge_gate"
    assert out[2] == "EDGE_MODEL_DOMINANT"
    assert out[3]["margin_shift"] == pytest.approx(0.0005)
    assert out[3]["before"] == pytest.approx(0.001)
    assert out[3]["after"] == pytest.approx(0.0015)


def test_edge_gate_fee_relax_split(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("RESEARCH_EDGE_GATE_EXPERIMENT_ENABLE", "1")
    monkeypatch.setenv("RESEARCH_EDGE_GATE_FEE_RELAX_BPS", "25")
    out = _research_only_edge_gate_overlay(
        0.001,
        0.0008,
        0.001,
        0.002,
        0.0025,
        True,
    )
    assert out[1] == "research_edge_gate"
    assert out[2] == "FEE_MODEL_DOMINANT"
    assert out[3]["fee_relax_bps"] == pytest.approx(25.0)
    assert out[3]["fee_relax_value"] == pytest.approx(0.000005)


def test_edge_gate_require_history_ready_blocks_no_history(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("RESEARCH_EDGE_GATE_EXPERIMENT_ENABLE", "1")
    monkeypatch.setenv("RESEARCH_EDGE_GATE_REQUIRE_HISTORY_READY", "1")
    out = _research_only_edge_gate_overlay(
        0.001,
        0.0008,
        0.003,
        0.002,
        0.0025,
        False,
    )
    assert out[0] == 0.001
    assert out[1] == "research_edge_gate"
    assert out[2] == "history_not_ready"
    assert out[3]["history_ready"] is False


def test_seed_trade_override_only_while_history_count_is_zero(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    _SEED_TRADES_ADMISSION_COUNT_BY_BUCKET.clear()
    allow, entry_decision, entry_reason, active = _apply_seed_trade_override(
        allow=False,
        entry_decision="hold",
        entry_decision_raw="buy",
        entry_reason="net_target_guard",
        history_count_used=0,
        bucket_key="BTCUSDTM|TRENDFOLLOWING|buy",
        seed_trades_enabled=True,
        seed_trades_limit=2,
    )
    assert allow is True
    assert entry_decision == "buy"
    assert entry_reason == "seed_trades_override"
    assert active is True


def test_seed_trade_history_count_for_override_collapses_to_zero_until_ready():
    assert _seed_trade_history_count_for_override(3, False) == 0
    assert _seed_trade_history_count_for_override(0, False) == 0


def test_seed_trade_history_count_for_override_keeps_ready_count():
    assert _seed_trade_history_count_for_override(3, True) == 3
    assert _seed_trade_history_count_for_override("2", True) == 2
    assert _seed_trade_history_count_for_override(None, True) == 0


def test_seed_trade_override_respects_limit_and_live_noop(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    _SEED_TRADES_ADMISSION_COUNT_BY_BUCKET.clear()
    allow, entry_decision, entry_reason, active = _apply_seed_trade_override(
        allow=False,
        entry_decision="hold",
        entry_decision_raw="buy",
        entry_reason="net_target_guard",
        history_count_used=0,
        bucket_key="BTCUSDTM|TRENDFOLLOWING|buy",
        seed_trades_enabled=True,
        seed_trades_limit=1,
    )
    assert allow is False
    assert entry_decision == "hold"
    assert entry_reason == "net_target_guard"
    assert active is False

    monkeypatch.delenv("LIVE", raising=False)
    _SEED_TRADES_ADMISSION_COUNT_BY_BUCKET.clear()
    _SEED_TRADES_ADMISSION_COUNT_BY_BUCKET["BTCUSDTM|TRENDFOLLOWING|buy"] = 1
    allow, entry_decision, entry_reason, active = _apply_seed_trade_override(
        allow=False,
        entry_decision="hold",
        entry_decision_raw="buy",
        entry_reason="net_target_guard",
        history_count_used=0,
        bucket_key="BTCUSDTM|TRENDFOLLOWING|buy",
        seed_trades_enabled=True,
        seed_trades_limit=1,
    )
    assert allow is False
    assert entry_decision == "hold"
    assert entry_reason == "net_target_guard"
    assert active is False


def test_edge_gate_debug_default_off(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.delenv("RESEARCH_EDGE_GATE_DEBUG", raising=False)
    payload = _research_only_edge_gate_debug(
        symbol="ETHUSDTM",
        strategy="TrendFollowing",
        regime="trend",
        entry_decision="buy",
        entry_reason="risk_or_prefilter_block",
        history_ready=True,
        trade_count=7,
        edge_metric=0.01,
        fee_metric=0.002,
    )
    assert payload is None


def test_edge_gate_debug_live_noop(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("RESEARCH_EDGE_GATE_DEBUG", "1")
    payload = _research_only_edge_gate_debug(
        symbol="ETHUSDTM",
        strategy="TrendFollowing",
        regime="trend",
        entry_decision="buy",
        entry_reason="risk_or_prefilter_block",
    )
    assert payload is None


def test_edge_gate_debug_builds_payload(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("RESEARCH_EDGE_GATE_DEBUG", "1")
    payload = _research_only_edge_gate_debug(
        symbol="ETHUSDTM",
        strategy="TrendFollowing",
        regime="trend",
        entry_decision="buy",
        entry_reason="risk_or_prefilter_block",
        prefilter_reason="strategy_blocklist",
        history_ready=True,
        trade_count=7,
        edge_metric=0.01,
        fee_metric=0.002,
        live_edge_proxy=0.03,
        profit_gate={"blocked": False},
        profit_gate_exploration={"exploration": True},
        alpha_status={"allow": True},
    )
    assert payload["symbol"] == "ETHUSDTM"
    assert payload["strategy"] == "TrendFollowing"
    assert payload["regime"] == "trend"
    assert payload["entry_decision"] == "buy"
    assert payload["entry_reason"] == "risk_or_prefilter_block"
    assert payload["prefilter_reason"] == "strategy_blocklist"
    assert payload["history_ready"] is True
    assert payload["trade_count"] == 7
    assert payload["edge_metric"] == pytest.approx(0.01)
    assert payload["fee_metric"] == pytest.approx(0.002)
    assert payload["live_edge_proxy"] == pytest.approx(0.03)
    assert payload["profit_gate"] == {"blocked": False}
    assert payload["profit_gate_exploration"] == {"exploration": True}
    assert payload["alpha_status"] == {"allow": True}


def test_tf_gate_debug_default_off(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.delenv("RESEARCH_TF_GATE_DEBUG", raising=False)
    payload = _research_only_tf_gate_debug(
        symbol="ETHUSDTM",
        strategy="TrendFollowing",
        regime="trend",
        score_ok=True,
        edge_ok=False,
        final_pass=False,
        threshold_edge=0.002,
        threshold_score=0.1,
        tf_reason="blocked_before_tf_gate_eval",
    )
    assert payload is None


def test_tf_gate_debug_live_noop(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("RESEARCH_TF_GATE_DEBUG", "1")
    payload = _research_only_tf_gate_debug(
        symbol="ETHUSDTM",
        strategy="TrendFollowing",
        regime="trend",
    )
    assert payload is None


def test_tf_gate_debug_builds_payload(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("RESEARCH_TF_GATE_DEBUG", "1")
    payload = _research_only_tf_gate_debug(
        symbol="ETHUSDTM",
        strategy="TrendFollowing",
        regime="trend",
        score_ok=True,
        edge_ok=None,
        final_pass=False,
        threshold_edge=0.002,
        threshold_score=0.1,
        tf_reason="blocked_before_tf_gate_eval",
        tf_rule_pass=False,
        tf_edge_ok=None,
        tf_score_ok=True,
        entry_expected_edge_after_fee=None,
        signal_score_abs=0.9,
        router_lead=None,
        tf_trend_eval_applies=True,
    )
    assert payload["symbol"] == "ETHUSDTM"
    assert payload["strategy"] == "TrendFollowing"
    assert payload["regime"] == "trend"
    assert payload["score_ok"] is True
    assert payload["edge_ok"] is None
    assert payload["final_pass"] is False
    assert payload["threshold_edge"] == pytest.approx(0.002)
    assert payload["threshold_score"] == pytest.approx(0.1)
    assert payload["tf_reason"] == "blocked_before_tf_gate_eval"
    assert payload["tf_rule_pass"] is False
    assert payload["tf_score_ok"] is True
    assert payload["signal_score_abs"] == pytest.approx(0.9)
    assert payload["tf_trend_eval_applies"] is True


def test_expected_edge_debug_default_off(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.delenv("RESEARCH_EXPECTED_EDGE_DEBUG", raising=False)
    payload = _research_only_expected_edge_debug(
        symbol="ETHUSDTM",
        strategy="TrendFollowing",
        regime="trend",
        entry_decision_raw="buy",
    )
    assert payload is None


def test_expected_edge_debug_live_noop(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("RESEARCH_EXPECTED_EDGE_DEBUG", "1")
    payload = _research_only_expected_edge_debug(
        symbol="ETHUSDTM",
        strategy="TrendFollowing",
        regime="trend",
        entry_decision_raw="buy",
    )
    assert payload is None


def test_expected_edge_debug_builds_payload(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("RESEARCH_EXPECTED_EDGE_DEBUG", "1")
    payload = _research_only_expected_edge_debug(
        symbol="ETHUSDTM",
        strategy="TrendFollowing",
        regime="trend",
        entry_decision_raw="buy",
        entry_expected_edge_after_fee=None,
        edge_metric=0.01,
        fee_metric=0.002,
        history_ready=False,
        trade_count=0,
        edge_reason="status_none",
        entry_decision="buy",
        live_edge_proxy=0.03,
    )
    assert payload["symbol"] == "ETHUSDTM"
    assert payload["strategy"] == "TrendFollowing"
    assert payload["regime"] == "trend"
    assert payload["entry_decision_raw"] == "buy"
    assert payload["entry_expected_edge_after_fee"] is None
    assert payload["status"] == "missing"
    assert payload["edge_metric"] == pytest.approx(0.01)
    assert payload["fee_metric"] == pytest.approx(0.002)
    assert payload["history_ready"] is False
    assert payload["trade_count"] == 0
    assert payload["edge_reason"] == "status_none"
    assert payload["entry_decision"] == "buy"
    assert payload["live_edge_proxy"] == pytest.approx(0.03)


def test_hold_transition_debug_default_off(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.delenv("RESEARCH_HOLD_TRANSITION_DEBUG", raising=False)
    payload = _research_only_hold_transition_debug(
        branch_name="current_side",
        symbol="ETHUSDTM",
        entry_decision_before="buy",
        entry_decision_after="hold",
        entry_reason=None,
        branch_fields={"current_side": {"side": "buy"}},
    )
    assert payload is None


def test_hold_transition_debug_live_noop(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("RESEARCH_HOLD_TRANSITION_DEBUG", "1")
    payload = _research_only_hold_transition_debug(
        branch_name="current_side",
        symbol="ETHUSDTM",
        entry_decision_before="buy",
        entry_decision_after="hold",
        entry_reason=None,
    )
    assert payload is None


def test_hold_transition_debug_builds_payload(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("RESEARCH_HOLD_TRANSITION_DEBUG", "1")
    payload = _research_only_hold_transition_debug(
        branch_name="current_side",
        symbol="ETHUSDTM",
        entry_decision_before="buy",
        entry_decision_after="hold",
        entry_reason=None,
        branch_fields={"current_side": {"side": "buy"}},
    )
    assert payload["branch"] == "current_side"
    assert payload["symbol"] == "ETHUSDTM"
    assert payload["entry_decision_before"] == "buy"
    assert payload["entry_decision_after"] == "hold"
    assert payload["entry_reason"] is None
    assert payload["branch_fields"] == {"current_side": {"side": "buy"}}


def test_net_target_guard_debug_default_off(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.delenv("RESEARCH_NET_TARGET_GUARD_DEBUG", raising=False)
    payload = _research_only_net_target_guard_debug(
        symbol="ETHUSDTM",
        strategy="TrendFollowing",
        entry_decision_raw="buy",
        entry_decision_before_guard="buy",
        entry_decision_after_guard="hold",
        expected_edge_after_fee=0.0,
        history_ready=False,
        trade_count=0,
        expected_net=0.0,
        target_net=0.1,
        target_net_base=0.1,
        tp_dist=0.01,
        fee_per_unit=0.001,
        amount=1.0,
        entry_min_net_to_stop_ratio=0.0,
        sl_price=None,
        rr_net=None,
        effective_entry_min_net_usdt_before=0.1,
        effective_entry_min_net_usdt_after=0.1,
        dynamic_adjustment_applied=False,
        final_blocked=True,
    )
    assert payload is None


def test_net_target_guard_debug_live_noop(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("RESEARCH_NET_TARGET_GUARD_DEBUG", "1")
    payload = _research_only_net_target_guard_debug(
        symbol="ETHUSDTM",
        strategy="TrendFollowing",
        entry_decision_raw="buy",
        entry_decision_before_guard="buy",
        entry_decision_after_guard="hold",
        expected_edge_after_fee=0.0,
        history_ready=False,
        trade_count=0,
        expected_net=0.0,
        target_net=0.1,
        target_net_base=0.1,
        tp_dist=0.01,
        fee_per_unit=0.001,
        amount=1.0,
        entry_min_net_to_stop_ratio=0.0,
        sl_price=None,
        rr_net=None,
        effective_entry_min_net_usdt_before=0.1,
        effective_entry_min_net_usdt_after=0.1,
        dynamic_adjustment_applied=False,
        final_blocked=True,
    )
    assert payload is None


def test_net_target_guard_debug_builds_payload(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("RESEARCH_NET_TARGET_GUARD_DEBUG", "1")
    payload = _research_only_net_target_guard_debug(
        symbol="ETHUSDTM",
        strategy="TrendFollowing",
        entry_decision_raw="buy",
        entry_decision_before_guard="buy",
        entry_decision_after_guard="hold",
        expected_edge_after_fee=0.0,
        history_ready=False,
        trade_count=0,
        expected_net=0.0,
        target_net=0.1,
        target_net_base=0.1,
        tp_dist=0.01,
        fee_per_unit=0.001,
        amount=1.0,
        entry_min_net_to_stop_ratio=0.0,
        sl_price=None,
        rr_net=None,
        effective_entry_min_net_usdt_before=0.1,
        effective_entry_min_net_usdt_after=0.1,
        dynamic_adjustment_applied=False,
        final_blocked=True,
    )
    assert payload["symbol"] == "ETHUSDTM"
    assert payload["strategy"] == "TrendFollowing"
    assert payload["entry_decision_raw"] == "buy"
    assert payload["entry_decision_before_guard"] == "buy"
    assert payload["entry_decision_after_guard"] == "hold"
    assert payload["expected_edge_after_fee"] == pytest.approx(0.0)
    assert payload["history_ready"] is False
    assert payload["trade_count"] == 0
    assert payload["expected_net"] == pytest.approx(0.0)
    assert payload["target_net"] == pytest.approx(0.1)
    assert payload["final_blocked"] is True
    assert payload["effective_entry_min_net_usdt_before"] == pytest.approx(0.1)
    assert payload["effective_entry_min_net_usdt_after"] == pytest.approx(0.1)
    assert payload["dynamic_adjustment_applied"] is False
