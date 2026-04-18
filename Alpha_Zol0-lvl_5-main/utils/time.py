def to_ms(ts):
    if ts is None:
        return None
    try:
        val = int(float(ts))
    except Exception:
        return None
    if val < 10_000_000_000:
        return val * 1000
    return val
