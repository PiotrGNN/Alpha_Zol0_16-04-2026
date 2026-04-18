from __future__ import annotations


def _normalize_side(value):
    txt = str(value or "").strip().lower()
    if txt in {"long", "buy"}:
        return "buy"
    if txt in {"short", "sell"}:
        return "sell"
    return txt or "unknown"


def _extract_symbol(payload: dict) -> str:
    symbol = payload.get("symbol")
    if symbol in (None, ""):
        pos = payload.get("position") or {}
        symbol = pos.get("symbol")
    return str(symbol or "UNKNOWN").strip().upper() or "UNKNOWN"


def _extract_side(payload: dict) -> str:
    side = payload.get("side")
    if side in (None, ""):
        pos = payload.get("position") or {}
        side = pos.get("side")
    return _normalize_side(side)


def resolve_strategy_identity(payload: dict):
    entry_edge = payload.get("entry_edge_over_fee") or {}
    pos = payload.get("position") or {}
    candidate_sources = [
        entry_edge.get("strategy"),
        payload.get("strategy"),
        pos.get("entry_main_strategy"),
        pos.get("strategy"),
    ]
    for candidate in candidate_sources:
        raw = str(candidate or "").strip()
        if not raw:
            continue
        upper = raw.upper()
        if upper == "__ALL__":
            return None, "UNRESOLVED", "strategy_is___ALL__"
        if upper == "UNKNOWN":
            return None, "UNRESOLVED", "fallback_unknown"
        return upper, "RESOLVED", "explicit_strategy"
    return None, "UNRESOLVED", "missing_strategy_field"


def build_canonical_bucket_key(payload: dict):
    symbol = _extract_symbol(payload)
    side = _extract_side(payload)
    strategy_identity, status, reason = resolve_strategy_identity(payload)
    canonical_bucket_key = None
    if status == "RESOLVED" and strategy_identity:
        canonical_bucket_key = f"{symbol}|{strategy_identity}|{side}"
    return {
        "canonical_bucket_key": canonical_bucket_key,
        "bucket_identity_status": status,
        "bucket_identity_reason": reason,
        "symbol": symbol,
        "side": side,
        "strategy_identity": strategy_identity,
    }
