from __future__ import annotations

from core.runtime_v2.admission_reachability import (
    admission_reachability_profile_payload,
)
from core.runtime_v2.contracts import QuoteTick
from core.runtime_v2.feature_engine import FeatureEngine
from core.runtime_v2.telemetry import TelemetryV2


def _tick(ts_ms: int, mid: float) -> QuoteTick:
    return QuoteTick(
        symbol="BTCUSDTM",
        ts_ms=ts_ms,
        bid=mid - 0.05,
        ask=mid + 0.05,
        mid=mid,
        spread_abs=0.1,
        spread_bps=(0.1 / mid) * 10000.0,
        best_bid_size=10.0,
        best_ask_size=10.0,
        raw={},
    )


def test_admission_reachability_profile_min_samples_paper_only(monkeypatch):
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.delenv("V2_MIN_PROFILE_SAMPLES", raising=False)
    monkeypatch.setenv("V2_PAPER_ADMISSION_REACHABILITY_PROFILE_ENABLE", "1")
    engine = FeatureEngine(history_size=16)
    frame = None
    for idx in range(4):
        frame = engine.ingest(_tick(ts_ms=3000 + idx * 1000, mid=200.0 + idx * 0.01))

    assert frame is not None
    assert frame.sample_count == 4
    assert frame.has_profile is True


def test_admission_reachability_profile_live_keeps_default_min_samples(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.delenv("V2_MIN_PROFILE_SAMPLES", raising=False)
    monkeypatch.setenv("V2_PAPER_ADMISSION_REACHABILITY_PROFILE_ENABLE", "1")
    engine = FeatureEngine(history_size=16)
    frame = None
    for idx in range(4):
        frame = engine.ingest(_tick(ts_ms=4000 + idx * 1000, mid=200.0 + idx * 0.01))

    assert frame is not None
    assert frame.sample_count == 4
    assert frame.has_profile is False


def test_admission_reachability_profile_payload_fields(monkeypatch):
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("V2_PAPER_ADMISSION_REACHABILITY_PROFILE_ENABLE", "1")

    payload = admission_reachability_profile_payload(
        default_v2_min_expected_net_ratio=0.0006,
        default_entry_min_net_usdt=0.12,
        default_v2_min_profile_samples=8,
    )

    assert payload["paper_admission_reachability_profile_enabled"] is True
    assert payload["paper_admission_reachability_profile_source"] == (
        "V2_PAPER_ADMISSION_REACHABILITY_PROFILE_ENABLE"
    )
    assert payload["effective_v2_min_expected_net_ratio"] == 0.00002
    assert payload["effective_entry_min_net_usdt"] == 0.02
    assert payload["effective_v2_min_profile_samples"] == 4
    assert payload["default_thresholds_preserved"] is False
    assert payload["live_override_blocked"] is False


def test_admission_reachability_profile_payload_live_override(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("V2_PAPER_ADMISSION_REACHABILITY_PROFILE_ENABLE", "1")

    payload = admission_reachability_profile_payload(
        default_v2_min_expected_net_ratio=0.0006,
        default_entry_min_net_usdt=0.12,
        default_v2_min_profile_samples=8,
    )

    assert payload["paper_admission_reachability_profile_enabled"] is False
    assert payload["effective_v2_min_expected_net_ratio"] == 0.0006
    assert payload["effective_entry_min_net_usdt"] == 0.12
    assert payload["effective_v2_min_profile_samples"] == 8
    assert payload["default_thresholds_preserved"] is True
    assert payload["live_override_blocked"] is True

def test_immediate_adverse_guard_telemetry_emits_evaluated_and_status(monkeypatch):
    captured = []

    def capture(self, event, payload):
        captured.append((event, payload))

    monkeypatch.setattr(TelemetryV2, "_emit", capture)
    telemetry = TelemetryV2(engine_version="v2")
    fields = {
        "immediate_adverse_guard_type": "SYMBOL_SIDE_PROFILE_QUARANTINE",
        "immediate_adverse_guard_reason": "profile_quarantined",
        "symbol": "SOLUSDTM",
        "side": "buy",
        "strategy": "TrendFollowingV2",
        "expected_net": 0.12,
        "probability": 0.99,
        "risk_score": 0.75,
        "guard_threshold": 0.5,
        "historical_immediate_adverse_rate": 0.75,
        "historical_tail_loss_net": -0.64,
    }

    telemetry.emit_immediate_adverse_guard(status="blocked", fields=fields)

    assert [event for event, _payload in captured] == [
        "immediate_adverse_guard_evaluated",
        "immediate_adverse_guard_blocked",
    ]
    payload = captured[-1][1]
    assert payload["immediate_adverse_guard_evaluated"] is True
    assert payload["immediate_adverse_guard_status"] == "blocked"
    assert payload["immediate_adverse_guard_type"] == "SYMBOL_SIDE_PROFILE_QUARANTINE"
    assert payload["immediate_adverse_guard_reason"] == "profile_quarantined"
    assert payload["historical_immediate_adverse_rate"] == 0.75
    assert payload["historical_tail_loss_net"] == -0.64

def test_shadow_verified_guard_telemetry_emits_rule_attribution(monkeypatch):
    captured = []

    def capture(self, event, payload):
        captured.append((event, payload))

    monkeypatch.setattr(TelemetryV2, "_emit", capture)
    telemetry = TelemetryV2(engine_version="v2")
    fields = {
        "shadow_verified_guard_rule_id": (
            "SOLUSDTM_buy_TrendFollowingV2_shadow_verified_20260606_000500"
        ),
        "shadow_verified_guard_reason": "verified_rule_matched",
        "shadow_verified_guard_symbol": "SOLUSDTM",
        "shadow_verified_guard_side": "buy",
        "shadow_verified_guard_strategy": "TrendFollowingV2",
        "shadow_verified_guard_source_artifact": (
            "analysis/immediate_adverse_shadow_verified_guard_candidates_long_shadow_current.json"
        ),
        "shadow_verified_guard_terminal_outcome_count": 18,
        "shadow_verified_guard_missed_winner_rate": 0.3333333333333333,
        "shadow_verified_guard_expected_net_benefit": 0.08687323999998789,
    }

    telemetry.emit_shadow_verified_guard(status="blocked", fields=fields)

    assert [event for event, _payload in captured] == [
        "shadow_verified_guard_evaluated",
        "shadow_verified_guard_blocked",
    ]
    payload = captured[-1][1]
    assert payload["shadow_verified_guard_evaluated"] is True
    assert payload["shadow_verified_guard_status"] == "blocked"
    assert (
        payload["shadow_verified_guard_rule_id"]
        == "SOLUSDTM_buy_TrendFollowingV2_shadow_verified_20260606_000500"
    )
    assert payload["shadow_verified_guard_source_artifact"].endswith(
        "immediate_adverse_shadow_verified_guard_candidates_long_shadow_current.json"
    )
    assert payload["shadow_verified_guard_missed_winner_rate"] == 0.3333333333333333
    assert payload["shadow_verified_guard_expected_net_benefit"] == 0.08687323999998789
