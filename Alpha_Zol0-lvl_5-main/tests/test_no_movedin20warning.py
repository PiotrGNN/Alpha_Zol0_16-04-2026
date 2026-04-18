import warnings
import importlib


def test_no_movedin20warning():
    # Reload module and assert SQLAlchemy moved-in-20 warning is not emitted
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        # reload to ensure import executes our compatibility block
        try:
            import core.db_models as dbm

            importlib.reload(dbm)
        except Exception as e:
            # If import fails, fail the test
            assert False, f"Import of core.db_models failed: {e}"
        # Check warnings
        msgs = []
        for x in w:
            cat = getattr(x, "category", None)
            cat_name = cat.__name__ if cat else str(type(x.message))
            msg = str(x.message)
            msgs.append((cat_name, msg))

        for cat, msg in msgs:
            assert "MovedIn20Warning" not in cat, f"Found moved warning: {cat}: {msg}"

        # Also ensure no message contains text about declarative_base moved
        found_declarative = any(
            "declarative_base" in msg or "declarative_base()" in msg for _, msg in msgs
        )
        # Keep the assert message wrapped
        # to avoid exceeding the line length limit
        assert (
            not found_declarative
        ), f"Found message mentioning declarative_base: {msgs}"
