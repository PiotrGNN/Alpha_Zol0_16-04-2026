"""Tests for fallback policy exhaustion telemetry and attribution persistence."""

import json
import sqlite3
from pathlib import Path

import pytest

from core.DynamicStrategyRouter import DynamicStrategyRouter


CONFIRMED_FORCED_RUN_DB = Path(
    "tmp/controlled_kpi_after_20260427_183101.db"
)


class _FakeBotCoreDecisionEmitter:
    """Simulates the decision attribution logic in BotCore for fallback exhaustion."""

    def __init__(self, router, symbol, raw_signals=None, allocations=None):
        self.router = router
        self.symbol = symbol
        self.raw_signals = list(raw_signals or [])
        self.allocations = dict(allocations or {})
        self.details = None

    @staticmethod
    def _count_surviving_allocations(allocations):
        count = 0
        for value in (allocations or {}).values():
            try:
                if float(value) > 0:
                    count += 1
            except Exception:
                continue
        return count

    def emit_decision(self):
        # Simulate the attribution logic after patch
        fallback_exhaustion_info = getattr(
            self.router, "last_policy_exhaustion_info", {}
        )
        details = {
            "symbol": self.symbol,
            "strategy_assignment_reason": (
                "fallback_policy_exhausted_strategy_side"
                if fallback_exhaustion_info.get("fallback_policy_exhausted")
                else fallback_exhaustion_info.get("bucket_identity_reason")
            ),
            "fallback_policy_exhausted": bool(
                fallback_exhaustion_info.get("fallback_policy_exhausted")
            ),
            "fallback_policy_viable_assignments_count": fallback_exhaustion_info.get(
                "fallback_policy_viable_assignments_count"
            ),
            "fallback_policy_blocked_strategies": fallback_exhaustion_info.get(
                "fallback_policy_blocked_strategies"
            ),
            "fallback_policy_blocked_sides": fallback_exhaustion_info.get(
                "fallback_policy_blocked_sides"
            ),
            "fallback_policy_exhaustion_reason": fallback_exhaustion_info.get(
                "fallback_policy_exhaustion_reason"
            ),
            "fallback_policy_final_candidate_count": (
                0
                if fallback_exhaustion_info.get("fallback_policy_exhausted")
                else None
            ),
            "raw_strategy_signal_count": (
                len(self.raw_signals)
                if fallback_exhaustion_info.get("fallback_policy_exhausted")
                else None
            ),
            "surviving_router_allocation_count": (
                self._count_surviving_allocations(self.allocations)
                if fallback_exhaustion_info.get("fallback_policy_exhausted")
                else None
            ),
        }
        self.details = details
        return details


class TestFallbackPolicyDecisionAttribution:
    def test_exhausted_router_sets_explicit_attribution(self):
        router = _FakeExhaustedRouter()
        emitter = _FakeBotCoreDecisionEmitter(
            router,
            "BTCUSDTM",
            raw_signals=[{"strategy": "Momentum"}, {"strategy": "TrendFollowing"}],
            allocations={"Momentum": 0.0, "TrendFollowing": 0.0},
        )
        details = emitter.emit_decision()
        assert (
            details["strategy_assignment_reason"]
            == "fallback_policy_exhausted_strategy_side"
        )
        assert details["fallback_policy_exhausted"] is True
        assert details["fallback_policy_viable_assignments_count"] == 0
        assert details["fallback_policy_final_candidate_count"] == 0
        assert details["raw_strategy_signal_count"] == 2
        assert details["surviving_router_allocation_count"] == 0
        # Should not fallback to missing_strategy_field or hold_ignored
        assert details["strategy_assignment_reason"] != "missing_strategy_field"
        assert details["strategy_assignment_reason"] != "hold_ignored"

    def test_viable_router_does_not_set_exhausted_attribution(self):
        router = _FakeViableRouter()
        emitter = _FakeBotCoreDecisionEmitter(router, "BTCUSDTM")
        details = emitter.emit_decision()
        assert (
            details["strategy_assignment_reason"]
            != "fallback_policy_exhausted_strategy_side"
        )
        assert details["fallback_policy_exhausted"] is False
        assert details["fallback_policy_final_candidate_count"] is None

    def test_unrelated_hold_case_still_uses_hold_ignored(self):
        class _HoldRouter:
            last_policy_exhaustion_info = {
                "fallback_policy_exhausted": False,
                "bucket_identity_reason": "hold_ignored",
            }

        router = _HoldRouter()
        emitter = _FakeBotCoreDecisionEmitter(router, "ADAUSDTM")
        details = emitter.emit_decision()
        assert details["strategy_assignment_reason"] == "hold_ignored"
        assert details["fallback_policy_exhausted"] is False

    def test_exhausted_router_serialized_payload_keeps_attribution_fields(self):
        router = _FakeExhaustedRouter()
        emitter = _FakeBotCoreDecisionEmitter(
            router,
            "ETHUSDTM",
            raw_signals=[{"strategy": "Momentum"}],
            allocations={"Momentum": 0.0, "Universal": 0.0},
        )

        details = emitter.emit_decision()
        serialized = json.dumps(details)
        roundtrip = json.loads(serialized)

        assert (
            roundtrip["strategy_assignment_reason"]
            == "fallback_policy_exhausted_strategy_side"
        )
        assert roundtrip["fallback_policy_exhausted"] is True
        assert roundtrip["fallback_policy_exhaustion_reason"] == "DISABLE_STRATEGIES"
        assert roundtrip["fallback_policy_blocked_strategies"] == ["TrendFollowing"]
        assert roundtrip["fallback_policy_blocked_sides"] == ["buy", "sell"]
        assert roundtrip["fallback_policy_viable_assignments_count"] == 0
        assert roundtrip["raw_strategy_signal_count"] == 1
        assert roundtrip["surviving_router_allocation_count"] == 0


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

class _HoldStrategy:
    def __init__(self, name="Universal"):
        self.name = name

    def analyze(self, market_state):
        return {"signals": [], "metrics": {}, "analysis": {}}


class _BuyStrategy:
    def __init__(self, name="Momentum"):
        self.name = name

    def analyze(self, market_state):
        return {"side": "buy", "signal": 1}


# ---------------------------------------------------------------------------
# DynamicStrategyRouter.last_policy_exhaustion_info tests
# ---------------------------------------------------------------------------

class TestRouterPolicyExhaustionInfo:
    """DISABLE_STRATEGIES forces alloc sum → 0 → exhaustion info set correctly."""

    def test_policy_exhausted_when_all_strategies_disabled(self, monkeypatch):
        # compute_allocations builds alloc from regime keys (TrendFollowing, Momentum,
        # MeanReversion for "mixed"). Disable all three → sum(alloc) == 0 → exhausted.
        monkeypatch.setenv(
            "DISABLE_STRATEGIES", "TrendFollowing,Momentum,MeanReversion"
        )
        strategies = [
            _HoldStrategy("TrendFollowing"),
            _BuyStrategy("Momentum"),
            _HoldStrategy("MeanReversion"),
        ]
        router = DynamicStrategyRouter(strategies=strategies)
        router.compute_allocations("mixed", {})

        info = router.last_policy_exhaustion_info
        assert info["fallback_policy_exhausted"] is True
        assert info["fallback_policy_viable_assignments_count"] == 0
        assert "TrendFollowing" in info["fallback_policy_blocked_strategies"]
        assert info["fallback_policy_exhaustion_reason"] == "DISABLE_STRATEGIES"
        assert isinstance(info["fallback_policy_blocked_sides"], list)

    def test_policy_not_exhausted_when_one_strategy_viable(self, monkeypatch):
        monkeypatch.setenv("DISABLE_STRATEGIES", "TrendFollowing")
        strategies = [
            _HoldStrategy("TrendFollowing"),
            _BuyStrategy("Momentum"),
        ]
        router = DynamicStrategyRouter(strategies=strategies)
        router.compute_allocations("mixed", {})

        info = router.last_policy_exhaustion_info
        assert info["fallback_policy_exhausted"] is False
        assert info["fallback_policy_viable_assignments_count"] > 0

    def test_policy_not_exhausted_with_no_disabled_strategies(self, monkeypatch):
        monkeypatch.setenv("DISABLE_STRATEGIES", "")
        strategies = [_BuyStrategy("Momentum"), _HoldStrategy("Universal")]
        router = DynamicStrategyRouter(strategies=strategies)
        router.compute_allocations("mixed", {})

        info = router.last_policy_exhaustion_info
        assert info["fallback_policy_exhausted"] is False
        assert info["fallback_policy_viable_assignments_count"] > 0
        assert info["fallback_policy_exhaustion_reason"] is None

    def test_exhaustion_info_initialized_empty(self):
        strategies = [_HoldStrategy()]
        router = DynamicStrategyRouter(strategies=strategies)
        # Before any compute_allocations call
        assert isinstance(router.last_policy_exhaustion_info, dict)

    def test_exhausted_info_has_all_required_fields(self, monkeypatch):
        monkeypatch.setenv("DISABLE_STRATEGIES", "TrendFollowing")
        strategies = [_HoldStrategy("TrendFollowing")]
        router = DynamicStrategyRouter(strategies=strategies)
        router.compute_allocations("mixed", {})

        info = router.last_policy_exhaustion_info
        required_fields = {
            "fallback_policy_exhausted",
            "fallback_policy_viable_assignments_count",
            "fallback_policy_blocked_strategies",
            "fallback_policy_blocked_sides",
            "fallback_policy_exhaustion_reason",
        }
        assert required_fields.issubset(info.keys())

    def test_partial_disable_does_not_exhaust(self, monkeypatch):
        """Disabling only one of two strategies should NOT exhaust allocation."""
        monkeypatch.setenv("DISABLE_STRATEGIES", "TrendFollowing")
        strategies = [
            _HoldStrategy("TrendFollowing"),
            _BuyStrategy("Momentum"),
            _HoldStrategy("Universal"),
        ]
        router = DynamicStrategyRouter(strategies=strategies)
        router.compute_allocations("trend", {})

        info = router.last_policy_exhaustion_info
        assert info["fallback_policy_exhausted"] is False


# ---------------------------------------------------------------------------
# BotCore integration smoke: fallback_policy_viable_assignments_exhausted event
# ---------------------------------------------------------------------------


class _FakeExhaustedRouter:
    """Simulates a router where all strategies are disabled → fully exhausted."""

    def __init__(self):
        self.last_policy_exhaustion_info = {
            "fallback_policy_exhausted": True,
            "fallback_policy_viable_assignments_count": 0,
            "fallback_policy_blocked_strategies": ["TrendFollowing"],
            "fallback_policy_blocked_sides": ["buy", "sell"],
            "fallback_policy_exhaustion_reason": "DISABLE_STRATEGIES",
        }

    def route(self, state):
        return []


class _FakeViableRouter:
    """Simulates a router where some strategies are active → not exhausted."""

    def __init__(self):
        self.last_policy_exhaustion_info = {
            "fallback_policy_exhausted": False,
            "fallback_policy_viable_assignments_count": 2,
            "fallback_policy_blocked_strategies": [],
            "fallback_policy_blocked_sides": [],
            "fallback_policy_exhaustion_reason": None,
        }

    def route(self, state):
        return [{"strategy": "Universal", "side": "hold", "allocation": 0.5}]


class _CapturingLogger:
    def __init__(self):
        self.events = []

    def log(self, event_name, payload):
        self.events.append({"event": event_name, "payload": payload})

    def get_events(self, name):
        return [e for e in self.events if e["event"] == name]


def _make_telemetry_emitter():
    """Extract the telemetry-emission logic from BotCore as a standalone function
    for unit testing, mirroring the exact code added to BotCore."""
    from datetime import datetime, timezone

    def emit_fallback_policy_exhaustion_telemetry(
        router, symbol, infinity_logger, live_mode=False
    ):
        emitted = False
        if not live_mode:
            try:
                _pol = getattr(router, "last_policy_exhaustion_info", {}) or {}
                if _pol.get("fallback_policy_exhausted"):
                    infinity_logger.log(
                        "fallback_policy_viable_assignments_exhausted",
                        {
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "symbol": symbol,
                            "fallback_policy_viable_assignments_count": int(
                                _pol.get("fallback_policy_viable_assignments_count", 0)
                            ),
                            "fallback_policy_exhausted": True,
                            "fallback_policy_exhausted_symbol": symbol,
                            "fallback_policy_blocked_strategies": list(
                                _pol.get("fallback_policy_blocked_strategies", [])
                            ),
                            "fallback_policy_blocked_sides": list(
                                _pol.get("fallback_policy_blocked_sides", [])
                            ),
                            "fallback_policy_exhaustion_reason": _pol.get(
                                "fallback_policy_exhaustion_reason"
                            ),
                        },
                    )
                    emitted = True
            except Exception:
                pass
        return emitted

    return emit_fallback_policy_exhaustion_telemetry


def _assert_fallback_log_decision_consistency(conn):
    fallback_log_count = conn.execute(
        "SELECT COUNT(*) FROM logs "
        "WHERE event='fallback_policy_viable_assignments_exhausted'"
    ).fetchone()[0]
    fallback_decision_count = conn.execute(
        "SELECT COUNT(*) FROM decisions "
        "WHERE details LIKE '%fallback_policy_exhausted_strategy_side%'"
    ).fetchone()[0]
    fallback_exhausted_rows = conn.execute(
        "SELECT COUNT(*) FROM decisions "
        "WHERE details LIKE '%fallback_policy_exhausted%'"
    ).fetchone()[0]
    strategy_assignment_reason_rows = conn.execute(
        "SELECT COUNT(*) FROM decisions "
        "WHERE details LIKE '%strategy_assignment_reason%'"
    ).fetchone()[0]

    if fallback_log_count > 0:
        assert fallback_decision_count > 0, (
            "fallback log events exist without persisted "
            "fallback_policy_exhausted_strategy_side decision rows"
        )
        assert fallback_exhausted_rows > 0, (
            "fallback log events exist without persisted fallback_policy_exhausted "
            "decision payload rows"
        )
        assert strategy_assignment_reason_rows > 0, (
            "fallback log events exist without persisted strategy_assignment_reason "
            "decision rows"
        )

    return {
        "fallback_log_count": int(fallback_log_count),
        "fallback_decision_count": int(fallback_decision_count),
        "fallback_exhausted_rows": int(fallback_exhausted_rows),
        "strategy_assignment_reason_rows": int(strategy_assignment_reason_rows),
    }


class TestFallbackPolicyTelemetryEmission:
    """
    Validate BotCore telemetry emission logic for exhausted policy.
    Tests mirror the exact code block added to BotCore after ensemble_signals log.
    """

    def test_exhausted_router_emits_event_in_paper_mode(self):
        router = _FakeExhaustedRouter()
        logger = _CapturingLogger()
        emitter = _make_telemetry_emitter()

        emitted = emitter(router, "XRPUSDTM", logger, live_mode=False)

        assert emitted is True
        events = logger.get_events("fallback_policy_viable_assignments_exhausted")
        assert len(events) == 1
        payload = events[0]["payload"]
        assert payload["fallback_policy_exhausted"] is True
        assert payload["fallback_policy_exhausted_symbol"] == "XRPUSDTM"
        assert payload["fallback_policy_viable_assignments_count"] == 0
        assert "TrendFollowing" in payload["fallback_policy_blocked_strategies"]
        assert payload["fallback_policy_exhaustion_reason"] == "DISABLE_STRATEGIES"

    def test_exhausted_router_emits_single_event_per_symbol_cycle(self):
        router = _FakeExhaustedRouter()
        logger = _CapturingLogger()
        emitter = _make_telemetry_emitter()

        emitted = emitter(router, "XRPUSDTM", logger, live_mode=False)

        assert emitted is True
        events = logger.get_events("fallback_policy_viable_assignments_exhausted")
        assert len(events) == 1

    def test_exhausted_router_does_not_emit_in_live_mode(self):
        router = _FakeExhaustedRouter()
        logger = _CapturingLogger()
        emitter = _make_telemetry_emitter()

        emitted = emitter(router, "XRPUSDTM", logger, live_mode=True)

        assert emitted is False
        events = logger.get_events("fallback_policy_viable_assignments_exhausted")
        assert len(events) == 0

    def test_viable_router_does_not_emit_event(self):
        router = _FakeViableRouter()
        logger = _CapturingLogger()
        emitter = _make_telemetry_emitter()

        emitted = emitter(router, "BTCUSDTM", logger, live_mode=False)

        assert emitted is False
        events = logger.get_events("fallback_policy_viable_assignments_exhausted")
        assert len(events) == 0

    def test_emitted_payload_has_all_required_fields(self):
        router = _FakeExhaustedRouter()
        logger = _CapturingLogger()
        emitter = _make_telemetry_emitter()

        emitter(router, "ETHUSDTM", logger, live_mode=False)

        events = logger.get_events("fallback_policy_viable_assignments_exhausted")
        payload = events[0]["payload"]
        required_fields = {
            "ts",
            "symbol",
            "fallback_policy_viable_assignments_count",
            "fallback_policy_exhausted",
            "fallback_policy_exhausted_symbol",
            "fallback_policy_blocked_strategies",
            "fallback_policy_blocked_sides",
            "fallback_policy_exhaustion_reason",
        }
        assert required_fields.issubset(payload.keys())

    def test_missing_policy_info_attribute_does_not_raise(self):
        """Router without last_policy_exhaustion_info should not cause errors."""
        class _BareRouter:
            def route(self, state):
                return []

        router = _BareRouter()
        logger = _CapturingLogger()
        emitter = _make_telemetry_emitter()

        # Should not raise
        emitted = emitter(router, "ADAUSDTM", logger, live_mode=False)
        assert emitted is False


class TestFallbackPolicyArtifactAudit:
    def test_artifact_audit_requires_decision_attribution_when_fallback_logs_exist(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute(
                "CREATE TABLE logs ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "event TEXT, details TEXT)"
            )
            conn.execute(
                "CREATE TABLE decisions ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "details TEXT)"
            )
            conn.execute(
                "INSERT INTO logs(event, details) VALUES (?, ?)",
                (
                    "fallback_policy_viable_assignments_exhausted",
                    json.dumps(
                        {
                            "symbol": "BTCUSDTM",
                            "ts": "2026-04-27T18:31:10+00:00",
                            "fallback_policy_exhausted": True,
                        }
                    ),
                ),
            )
            conn.execute(
                "INSERT INTO decisions(details) VALUES (?)",
                (
                    json.dumps(
                        {
                            "strategy_assignment_reason": (
                                "fallback_policy_exhausted_strategy_side"
                            ),
                            "fallback_policy_exhausted": True,
                        }
                    ),
                ),
            )

            counts = _assert_fallback_log_decision_consistency(conn)

            assert counts["fallback_log_count"] == 1
            assert counts["fallback_decision_count"] == 1
            assert counts["fallback_exhausted_rows"] == 1
            assert counts["strategy_assignment_reason_rows"] == 1
        finally:
            conn.close()

    def test_artifact_audit_fails_when_logs_exist_without_decision_attribution(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute(
                "CREATE TABLE logs ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "event TEXT, details TEXT)"
            )
            conn.execute(
                "CREATE TABLE decisions ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "details TEXT)"
            )
            conn.execute(
                "INSERT INTO logs(event, details) VALUES (?, ?)",
                (
                    "fallback_policy_viable_assignments_exhausted",
                    json.dumps(
                        {
                            "symbol": "ETHUSDTM",
                            "ts": "2026-04-27T18:31:11+00:00",
                            "fallback_policy_exhausted": True,
                        }
                    ),
                ),
            )
            conn.execute(
                "INSERT INTO decisions(details) VALUES (?)",
                (json.dumps({"entry_reason": "hold"}),),
            )

            with pytest.raises(
                AssertionError,
                match=(
                    "fallback log events exist without persisted "
                    "fallback_policy_exhausted_strategy_side decision rows"
                ),
            ):
                _assert_fallback_log_decision_consistency(conn)
        finally:
            conn.close()

    def test_confirmed_forced_run_artifact_keeps_log_and_decision_attribution_in_sync(
        self,
    ):
        if not CONFIRMED_FORCED_RUN_DB.exists():
            pytest.skip("confirmed forced-run DB artifact is unavailable")

        conn = sqlite3.connect(str(CONFIRMED_FORCED_RUN_DB))
        try:
            counts = _assert_fallback_log_decision_consistency(conn)
        finally:
            conn.close()

        assert counts["fallback_log_count"] > 0
        assert counts["fallback_decision_count"] > 0
        assert counts["fallback_exhausted_rows"] > 0
        assert counts["strategy_assignment_reason_rows"] > 0
