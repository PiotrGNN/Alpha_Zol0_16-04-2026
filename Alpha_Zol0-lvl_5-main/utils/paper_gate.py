from datetime import datetime, timedelta, timezone

_state = {
    "neg_count": 0,
    "below_target_count": 0,
    "active_until": None,
    "reason": None,
    "mode": None,
    "trigger_count": 0,
}


def _expire_if_needed(now):
    active_until = _state.get("active_until")
    if active_until and now >= active_until:
        _state["active_until"] = None
        _state["reason"] = None
        _state["mode"] = None
        _state["trigger_count"] = 0


def reset_state():
    _state["neg_count"] = 0
    _state["below_target_count"] = 0
    _state["active_until"] = None
    _state["reason"] = None
    _state["mode"] = None
    _state["trigger_count"] = 0


def update_gate(
    net_pnl_15m,
    now=None,
    cooldown_minutes=15,
    target=0.5,
):
    now = now or datetime.now(timezone.utc)
    _expire_if_needed(now)
    if _state.get("active_until") and now < _state["active_until"]:
        return get_state(now)
    if net_pnl_15m is None:
        _state["neg_count"] = 0
        _state["below_target_count"] = 0
        return get_state(now)
    if net_pnl_15m < 0:
        _state["neg_count"] += 1
    else:
        _state["neg_count"] = 0
    if net_pnl_15m < target:
        _state["below_target_count"] += 1
    else:
        _state["below_target_count"] = 0
    if _state["neg_count"] >= 2:
        _state["active_until"] = now + timedelta(minutes=cooldown_minutes)
        _state["reason"] = "net_pnl_15m_negative_twice"
        _state["mode"] = "HARD_NEGATIVE"
        _state["trigger_count"] = _state["neg_count"]
        _state["neg_count"] = 0
        _state["below_target_count"] = 0
    elif _state["below_target_count"] >= 4:
        _state["active_until"] = now + timedelta(minutes=cooldown_minutes)
        _state["reason"] = "net_pnl_15m_below_target"
        _state["mode"] = "SOFT_BELOW_TARGET"
        _state["trigger_count"] = _state["below_target_count"]
        _state["neg_count"] = 0
        _state["below_target_count"] = 0
    return get_state(now)


def get_state(now=None):
    now = now or datetime.now(timezone.utc)
    _expire_if_needed(now)
    active = _state.get("active_until") is not None and now < _state["active_until"]
    return {
        "active": active,
        "reason": _state.get("reason"),
        "mode": _state.get("mode"),
        "trigger_count": _state.get("trigger_count"),
        "active_until": (
            _state.get("active_until").isoformat()
            if _state.get("active_until")
            else None
        ),
    }
