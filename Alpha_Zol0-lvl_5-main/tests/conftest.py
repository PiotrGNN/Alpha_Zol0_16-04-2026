import os
import sys
import gc
import warnings

import pytest

try:
    from sklearn.exceptions import InconsistentVersionWarning
except Exception:
    InconsistentVersionWarning = None

try:
    from urllib3.exceptions import SystemTimeWarning
except Exception:
    SystemTimeWarning = None

# Ensure project root (Alpha_Zol0-lvl_5-main) is on sys.path for imports
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# Ensure only a single project root entry to avoid duplicated nested imports
# Ensure ROOT is first entry in sys.path so imports resolve to correct project
if not sys.path or sys.path[0] != ROOT:
    if ROOT in sys.path:
        sys.path.remove(ROOT)
    sys.path.insert(0, ROOT)
# Remove paths that include the project directory name twice
# (nested duplicate)
for p in list(sys.path[1:]):
    try:
        norm = os.path.normcase(p)
        if norm.count(os.path.normcase("Alpha_Zol0-lvl_5-main")) > 1:
            try:
                sys.path.remove(p)
            except ValueError:
                pass
    except Exception:
        continue

if InconsistentVersionWarning is not None:
    warnings.filterwarnings(
        "ignore",
        message=(
            r"Trying to unpickle estimator .* from version .* "
            r"when using version .*"
        ),
        category=InconsistentVersionWarning,
    )

warnings.filterwarnings(
    "ignore",
    message=r"\[.*\] WARNING: .*",
    category=UserWarning,
)

if SystemTimeWarning is not None:
    warnings.filterwarnings(
        "ignore",
        message=r"System time is way off .*",
        category=SystemTimeWarning,
    )


@pytest.fixture(autouse=True)
def _collect_garbage_after_test():
    yield
    gc.collect()
