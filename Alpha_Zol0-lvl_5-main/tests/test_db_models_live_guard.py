"""
P2-4  _resolve_database_url() raises RuntimeError when LIVE=1 and no DATABASE_URL.
"""
import importlib
import pytest


def test_resolve_database_url_raises_when_live_without_url(monkeypatch):
    """
    When LIVE=1 and DATABASE_URL is absent, reloading core.db_models must
    raise RuntimeError(DATABASE_URL is required when LIVE=1...).
    This guards against accidental use of a missing production connection string.
    """
    # Load module safely first (ensures it is in sys.modules for reload)
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import core.db_models as dbm
    importlib.reload(dbm)  # baseline load with LIVE=0

    # Now set LIVE=1 and verify reload raises
    monkeypatch.setenv("LIVE", "1")
    with pytest.raises(RuntimeError, match="DATABASE_URL is required when LIVE=1"):
        importlib.reload(dbm)


def test_resolve_database_url_succeeds_when_live_with_url(monkeypatch):
    """LIVE=1 with a valid DATABASE_URL must not raise."""
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")

    import core.db_models as dbm

    # Should not raise
    importlib.reload(dbm)


def test_resolve_database_url_defaults_to_sqlite_when_live_is_zero(monkeypatch):
    """LIVE=0 with no DATABASE_URL must silently fall back to SQLite."""
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    import core.db_models as dbm

    importlib.reload(dbm)  # must not raise
    assert dbm.DATABASE_URL.startswith("sqlite"), (
        f"Expected SQLite fallback URL, got: {dbm.DATABASE_URL}"
    )
