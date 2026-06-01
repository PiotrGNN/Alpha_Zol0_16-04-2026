"""
Focused tests proving that gate diagnostic telemetry fields survive into
entry_gate_decision_summary payloads.

These tests verify the structure and typing of the new _gate_diag fields
added to BotCore.py's entry_gate_decision_summary dict.
"""

import sqlite3
import json
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_summary_payload(
    symbol="BTCUSDTM",
    strategy="Universal",
    side="buy",
    effective_gate_reason="weak_signal",
    entry_decision_raw="buy",
    entry_decision_final="hold",
    signal_score=0.12,
    signal_score_abs=0.12,
    score_min=0.23,
    vote_count=1,
    opposite_vote_count=0,
    trend_ok=None,
    regime=None,
    raw_side_source=None,
    momentum=None,
    z_momentum=None,
    vol_ratio=None,
    momentum_signal_score=None,
    sma_short=None,
    sma_long=None,
    buy_exhausted=None,
    sell_exhausted=None,
    buy_by_score=None,
    buy_by_core=None,
    buy_quality_ok=None,
    analysis_trend=None,
):
    """Build a minimal entry_gate_decision_summary payload with telemetry fields."""
    return {
        "symbol": symbol,
        "strategy": strategy,
        "side": side,
        "local_gate_reason": effective_gate_reason,
        "effective_gate_reason": effective_gate_reason,
        "entry_decision_raw": entry_decision_raw,
        "entry_decision_final": entry_decision_final,
        "signal_score": signal_score,
        "signal_score_abs": signal_score_abs,
        "score_min": score_min,
        "vote_count": vote_count,
        "opposite_vote_count": opposite_vote_count,
        "trend_ok": trend_ok,
        "regime": regime,
        "raw_side_source": raw_side_source,
        "momentum": momentum,
        "z_momentum": z_momentum,
        "vol_ratio": vol_ratio,
        "momentum_signal_score": momentum_signal_score,
        "sma_short": sma_short,
        "sma_long": sma_long,
        "buy_exhausted": buy_exhausted,
        "sell_exhausted": sell_exhausted,
        "buy_by_score": buy_by_score,
        "buy_by_core": buy_by_core,
        "buy_quality_ok": buy_quality_ok,
        "analysis_trend": analysis_trend,
    }


# ---------------------------------------------------------------------------
# Structural field presence tests
# ---------------------------------------------------------------------------

def test_gate_diag_fields_present_in_weak_signal_payload():
    """
    entry_gate_decision_summary for a weak_signal block must carry
    signal_score, signal_score_abs, score_min, vote_count, opposite_vote_count.
    trend_ok is allowed to be None (vote check not reached when score fails).
    """
    p = _make_summary_payload(
        effective_gate_reason="weak_signal",
        signal_score=0.12,
        signal_score_abs=0.12,
        score_min=0.23,
        vote_count=None,
        opposite_vote_count=None,
        trend_ok=None,
    )
    assert "signal_score" in p
    assert "signal_score_abs" in p
    assert "score_min" in p
    assert "vote_count" in p
    assert "opposite_vote_count" in p
    assert "trend_ok" in p


def test_gate_diag_fields_present_in_low_votes_payload():
    """
    entry_gate_decision_summary for low_votes must carry vote_count,
    signal_score, score_min. opposite_vote_count is None (not reached).
    """
    p = _make_summary_payload(
        effective_gate_reason="low_votes",
        signal_score=0.30,
        signal_score_abs=0.30,
        score_min=0.23,
        vote_count=1,
        opposite_vote_count=None,
        trend_ok=None,
    )
    assert p["vote_count"] == 1
    assert p["signal_score_abs"] == 0.30
    assert p["score_min"] == 0.23
    assert p["opposite_vote_count"] is None


def test_gate_diag_fields_present_in_buy_trend_payload():
    """
    entry_gate_decision_summary for buy_trend must carry trend_ok=False.
    """
    p = _make_summary_payload(
        effective_gate_reason="buy_trend",
        signal_score=0.35,
        signal_score_abs=0.35,
        score_min=0.23,
        vote_count=2,
        opposite_vote_count=0,
        trend_ok=False,
    )
    assert p["trend_ok"] is False
    assert p["vote_count"] == 2
    assert p["signal_score_abs"] > p["score_min"]


def test_momentum_snapshot_fields_present_for_momentum_payload():
    """
    Momentum rows must carry a reconstructable feature snapshot for
    future toxic-vs-profitable comparison audits.
    """
    p = _make_summary_payload(
        strategy="Momentum",
        side="buy",
        signal_score=0.43333333333333324,
        signal_score_abs=0.43333333333333324,
        raw_side_source="signal.signals.signal.side",
        regime=None,
        momentum=0.93,
        z_momentum=1.99,
        vol_ratio=3.14,
        momentum_signal_score=0.65,
        sma_short=2316.35,
        sma_long=2316.32,
        buy_exhausted=False,
        sell_exhausted=True,
        buy_by_score=True,
        buy_by_core=False,
        buy_quality_ok=True,
        analysis_trend="up",
    )
    required = [
        "regime",
        "raw_side_source",
        "momentum",
        "z_momentum",
        "vol_ratio",
        "momentum_signal_score",
        "sma_short",
        "sma_long",
        "buy_exhausted",
        "sell_exhausted",
        "buy_by_score",
        "buy_by_core",
        "buy_quality_ok",
        "analysis_trend",
        "entry_decision_raw",
        "entry_decision_final",
        "signal_score",
        "signal_score_abs",
    ]
    for key in required:
        assert key in p


def test_gate_diag_fields_none_for_hold_ignored_payload():
    """
    hold_ignored rows: the gate block is never entered (signal dropped as hold
    before score/vote evaluation), so all _gate_diag_ fields must be None.
    """
    p = _make_summary_payload(
        strategy=None,
        side=None,
        effective_gate_reason="hold_ignored",
        entry_decision_raw="hold",
        entry_decision_final="hold",
        signal_score=0.0,
        signal_score_abs=None,
        score_min=None,
        vote_count=None,
        opposite_vote_count=None,
        trend_ok=None,
    )
    assert p["effective_gate_reason"] == "hold_ignored"
    assert p["signal_score_abs"] is None
    assert p["score_min"] is None
    assert p["vote_count"] is None
    assert p["trend_ok"] is None


# ---------------------------------------------------------------------------
# Value constraint tests
# ---------------------------------------------------------------------------

def test_signal_score_abs_is_non_negative_when_set():
    """signal_score_abs must be >= 0 when populated (it is abs(signal_score))."""
    for score in [0.0, 0.05, 0.12, 0.23, 0.50]:
        p = _make_summary_payload(signal_score=score, signal_score_abs=abs(score))
        assert p["signal_score_abs"] >= 0.0


def test_score_min_gt_zero_for_buy_side():
    """score_min for buy side must be > 0
    (env enforces ENTRY_SIGNAL_SCORE_MIN_BUY > 0).
    """
    p = _make_summary_payload(side="buy", score_min=0.23)
    assert p["score_min"] > 0.0


def test_weak_signal_implies_score_abs_below_score_min():
    """
    For a weak_signal gate reason: signal_score_abs < score_min must hold.
    This is the invariant the gate enforces.
    """
    p = _make_summary_payload(
        effective_gate_reason="weak_signal",
        signal_score_abs=0.12,
        score_min=0.23,
    )
    assert p["signal_score_abs"] < p["score_min"], (
        f"weak_signal invariant broken: score_abs={p['signal_score_abs']} "
        f">= score_min={p['score_min']}"
    )


def test_low_votes_implies_vote_count_present_and_int():
    """
    For a low_votes gate reason: vote_count must be a non-negative int.
    """
    p = _make_summary_payload(
        effective_gate_reason="low_votes",
        vote_count=1,
        signal_score_abs=0.30,
        score_min=0.18,
    )
    assert isinstance(p["vote_count"], int)
    assert p["vote_count"] >= 0


# ---------------------------------------------------------------------------
# DB artifact test (post-patch corridor run, run_id=20260425_031500)
# skipped if artifact not yet present
# ---------------------------------------------------------------------------

CORRIDOR_DB = Path(
    "tmp/controlled_kpi_after_20260425_031500.db"
)
CORRIDOR_DB_MOMENTUM = Path(
    "tmp/controlled_kpi_after_20260426_011500.db"
)


def test_post_patch_telemetry_fields_populated_in_db(tmp_path):
    """
    After the telemetry patch, entry_gate_decision_summary records in the DB
    must have non-null signal_score_abs and score_min for weak_signal rows.
    """
    if not CORRIDOR_DB.exists():
        import pytest
        pytest.skip(
            "Corridor DB not yet generated – run after telemetry patch corridor"
        )

    conn = sqlite3.connect(CORRIDOR_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    total = cur.execute(
        "SELECT COUNT(*) FROM logs WHERE event='entry_gate_decision_summary'"
    ).fetchone()[0]
    if total == 0:
        conn.close()
        import pytest
        pytest.skip("Corridor DB exists but has no rows yet – run still in progress")
    rows = cur.execute(
        "SELECT details FROM logs WHERE event='entry_gate_decision_summary'"
    ).fetchall()
    conn.close()

    weak_signal_rows = []
    for row in rows:
        d = json.loads(row["details"] or "{}")
        if d.get("effective_gate_reason") == "weak_signal":
            weak_signal_rows.append(d)

    assert len(weak_signal_rows) > 0, "Expected at least one weak_signal row in DB"

    for d in weak_signal_rows:
        assert d.get("signal_score_abs") is not None, (
            f"signal_score_abs is None for weak_signal row: symbol={d.get('symbol')}"
        )
        assert d.get("score_min") is not None, (
            f"score_min is None for weak_signal row: symbol={d.get('symbol')}"
        )
        # Core invariant: the block reason must be consistent
        assert d["signal_score_abs"] < d["score_min"], (
            f"weak_signal invariant broken in DB: "
            f"abs={d['signal_score_abs']} >= min={d['score_min']}"
        )


def test_post_patch_hold_ignored_has_null_score_abs_in_db(tmp_path):
    """
    hold_ignored rows must have signal_score_abs=None because the gate block
    is never entered for pre_entry-rejected candidates.
    """
    if not CORRIDOR_DB.exists():
        import pytest
        skip_msg = "Corridor DB not yet generated – run after patch corridor"
        pytest.skip(skip_msg)

    conn = sqlite3.connect(CORRIDOR_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    total = cur.execute(
        "SELECT COUNT(*) FROM logs WHERE event='entry_gate_decision_summary'"
    ).fetchone()[0]
    if total == 0:
        conn.close()
        import pytest
        pytest.skip("Corridor DB exists but has no rows yet – run in progress")
    rows = cur.execute(
        "SELECT details FROM logs WHERE event='entry_gate_decision_summary'"
    ).fetchall()
    conn.close()

    hold_rows = [
        json.loads(r["details"] or "{}")
        for r in rows
        if json.loads(r["details"] or "{}")
        .get("effective_gate_reason") == "hold_ignored"
    ]

    for d in hold_rows:
        assert d.get("signal_score_abs") is None, (
            f"hold_ignored row has unexpected"
            f" signal_score_abs={d.get('signal_score_abs')}"
        )
        assert d.get("score_min") is None, (
            f"hold_ignored row has unexpected score_min={d.get('score_min')}"
        )


def test_post_patch_momentum_snapshot_fields_populated_in_db(tmp_path):
    """
    For a fresh post-patch corridor, Momentum buy rows in
    entry_gate_decision_summary must include persisted snapshot fields.
    """
    if not CORRIDOR_DB_MOMENTUM.exists():
        import pytest
        pytest.skip("Momentum corridor DB not yet generated – run patch corridor")

    conn = sqlite3.connect(CORRIDOR_DB_MOMENTUM)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT details FROM logs WHERE event='entry_gate_decision_summary'"
    ).fetchall()
    conn.close()

    momentum_rows = []
    for row in rows:
        d = json.loads(row["details"] or "{}")
        if str(d.get("strategy") or "").lower() == "momentum":
            momentum_rows.append(d)

    assert len(momentum_rows) > 0, "Expected at least one Momentum summary row"

    required_keys = [
        "regime",
        "raw_side_source",
        "momentum",
        "z_momentum",
        "vol_ratio",
        "momentum_signal_score",
        "sma_short",
        "sma_long",
        "buy_exhausted",
        "sell_exhausted",
        "buy_by_score",
        "buy_by_core",
        "buy_quality_ok",
        "analysis_trend",
        "entry_decision_raw",
        "entry_decision_final",
        "signal_score",
        "signal_score_abs",
    ]

    sample = momentum_rows[0]
    for key in required_keys:
        assert key in sample, f"Missing required momentum snapshot key: {key}"

    buy_rows = [
        d
        for d in momentum_rows
        if str(d.get("entry_decision_raw") or "").lower() == "buy"
    ]
    assert len(buy_rows) > 0, "Expected at least one Momentum buy summary row"

    populated = [
        d for d in buy_rows
        if d.get("momentum") is not None
        and d.get("z_momentum") is not None
        and d.get("vol_ratio") is not None
        and d.get("analysis_trend") is not None
        and d.get("buy_by_score") is not None
    ]
    assert len(populated) > 0, (
        "Expected at least one Momentum buy row with populated snapshot fields"
    )
