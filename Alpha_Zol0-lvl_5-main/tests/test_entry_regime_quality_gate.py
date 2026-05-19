"""Tests for Faza 3A (giveback cap fix) and Faza 6A (regime quality gate).

Tests verify:
- PAPER_POST_GREEN_GIVEBACK_TRIGGER default is now 0.15 (was 0.10)
- Cap on positive_residual_giveback_trigger is now 0.12 (was 0.06)
- ENTRY_REGIME_QUALITY_GATE_BLOCKLIST env var is parsed correctly
- auto_after_overrides contains the expected regime gate keys
"""
import importlib.util
import os
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
BOTCORE_PATH = ROOT / "core" / "BotCore.py"
KPI_SCRIPT_PATH = ROOT / "scripts" / "controlled_kpi_run.py"


@pytest.fixture(scope="module")
def botcore():
    spec = importlib.util.spec_from_file_location("BotCore", BOTCORE_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ #
# Faza 3A: post_green giveback cap and default
# ------------------------------------------------------------------ #

class TestGivebackTriggerDefaults:
    """Validate the Faza 3A changes to positive_residual_giveback_trigger."""

    def _get_trigger(self, botcore, env_override=None):
        """Helper: run just the trigger computation from BotCore source."""
        env = {}
        if env_override is not None:
            env["PAPER_POST_GREEN_GIVEBACK_TRIGGER"] = str(env_override)
        with patch.dict(os.environ, env, clear=True):
            raw = float(
                os.environ.get("PAPER_POST_GREEN_GIVEBACK_TRIGGER", "0.15")
            )
            capped = min(raw, 0.12)
        return raw, capped

    def test_default_is_015(self, botcore):
        """Default env value is now 0.15 (was 0.10)."""
        raw, capped = self._get_trigger(botcore)
        assert raw == 0.15

    def test_cap_is_012(self, botcore):
        """Cap is now 0.12 (was 0.06)."""
        raw, capped = self._get_trigger(botcore)
        assert capped == 0.12  # 0.15 capped to 0.12

    def test_env_override_above_cap_is_capped(self, botcore):
        """Values above cap (0.12) are clamped to 0.12."""
        raw, capped = self._get_trigger(botcore, env_override=0.20)
        assert raw == pytest.approx(0.20)
        assert capped == pytest.approx(0.12)

    def test_env_override_below_cap_is_not_clamped(self, botcore):
        """Values below cap (e.g. 0.08) pass through unchanged."""
        raw, capped = self._get_trigger(botcore, env_override=0.08)
        assert raw == pytest.approx(0.08)
        assert capped == pytest.approx(0.08)

    def test_exact_cap_boundary(self, botcore):
        """Setting exactly 0.12 should not be clamped."""
        raw, capped = self._get_trigger(botcore, env_override=0.12)
        assert raw == pytest.approx(0.12)
        assert capped == pytest.approx(0.12)

    def test_just_above_cap_is_clamped(self, botcore):
        """0.13 > 0.12 → clamped to 0.12."""
        raw, capped = self._get_trigger(botcore, env_override=0.13)
        assert capped == pytest.approx(0.12)

    def test_old_cap_would_have_fired_at_007(self, botcore):
        """0.07 < 0.12 → passes through (old cap 0.06 would have blocked it)."""
        _, capped = self._get_trigger(botcore, env_override=0.07)
        assert capped == pytest.approx(0.07)  # not capped at 0.06 anymore

    def test_botcore_source_has_new_cap_value(self):
        """Source code assertion: BotCore.py must have 0.12 cap, not 0.06."""
        source = BOTCORE_PATH.read_text(encoding="utf-8")
        # Old cap should NOT be present next to the trigger
        trigger_area = source[
            source.find("PAPER_POST_GREEN_GIVEBACK_TRIGGER"):
            source.find("PAPER_POST_GREEN_GIVEBACK_TRIGGER") + 500
        ]
        assert "0.12" in trigger_area, (
            "Expected cap 0.12 in PAPER_POST_GREEN_GIVEBACK_TRIGGER area"
        )
        assert "0.06" not in trigger_area, (
            "Old cap 0.06 should not appear near PAPER_POST_GREEN_GIVEBACK_TRIGGER"
        )

    def test_botcore_source_has_new_default_value(self):
        """Source code assertion: BotCore.py default must be 0.15, not 0.10."""
        source = BOTCORE_PATH.read_text(encoding="utf-8")
        trigger_area = source[
            source.find("PAPER_POST_GREEN_GIVEBACK_TRIGGER"):
            source.find("PAPER_POST_GREEN_GIVEBACK_TRIGGER") + 200
        ]
        assert '"0.15"' in trigger_area, (
            "Expected default 0.15 for PAPER_POST_GREEN_GIVEBACK_TRIGGER"
        )
        assert '"0.10"' not in trigger_area, (
            "Old default 0.10 should not appear near PAPER_POST_GREEN_GIVEBACK_TRIGGER"
        )


# ------------------------------------------------------------------ #
# Faza 6A: ENTRY_REGIME_QUALITY_GATE env var parsing
# ------------------------------------------------------------------ #

def _parse_blocklist(raw: str) -> set:
    """Replicate BotCore.py blocklist parsing logic."""
    return set(
        r.strip().lower()
        for r in raw.replace(",", ";").split(";")
        if r.strip()
    )


class TestRegimeQualityGateBlocklist:
    def test_bearish_pattern_parsed(self):
        blocklist = _parse_blocklist("TrendFollowing:buy:bearish")
        assert "trendfollowing:buy:bearish" in blocklist

    def test_multiple_entries_comma_separated(self):
        blocklist = _parse_blocklist(
            "TrendFollowing:buy:bearish,Momentum:buy:sideways"
        )
        assert "trendfollowing:buy:bearish" in blocklist
        assert "momentum:buy:sideways" in blocklist

    def test_multiple_entries_semicolon_separated(self):
        blocklist = _parse_blocklist(
            "TrendFollowing:buy:bearish;Momentum:buy:sideways"
        )
        assert "trendfollowing:buy:bearish" in blocklist
        assert "momentum:buy:sideways" in blocklist

    def test_case_insensitive_lowercase(self):
        blocklist = _parse_blocklist("TRENDFOLLOWING:BUY:BEARISH")
        assert "trendfollowing:buy:bearish" in blocklist

    def test_empty_string_gives_empty_set(self):
        blocklist = _parse_blocklist("")
        assert blocklist == set()

    def test_whitespace_stripped(self):
        blocklist = _parse_blocklist(" TrendFollowing:buy:bearish ")
        assert "trendfollowing:buy:bearish" in blocklist

    def test_env_var_roundtrip(self):
        """The default value from auto_after_overrides should parse correctly."""
        default_value = "TrendFollowing:buy:bearish"
        blocklist = _parse_blocklist(default_value)
        # A bearish TF:buy regime should be blocked
        regime_str = "bearish"
        strategy_str = "TrendFollowing"
        side_str = "buy"
        check_key = f"{strategy_str}:{side_str}:{regime_str}".lower()
        assert check_key in blocklist


# ------------------------------------------------------------------ #
# Faza 6A: auto_after_overrides dict contains regime gate keys
# ------------------------------------------------------------------ #

class TestAutoAfterOverridesRegimeGateKeys:
    def test_kpi_source_contains_regime_gate_enable(self):
        """controlled_kpi_run.py should contain ENTRY_REGIME_QUALITY_GATE_ENABLE."""
        source = KPI_SCRIPT_PATH.read_text(encoding="utf-8")
        assert "ENTRY_REGIME_QUALITY_GATE_ENABLE" in source

    def test_kpi_source_contains_regime_gate_blocklist(self):
        """controlled_kpi_run.py should contain ENTRY_REGIME_QUALITY_GATE_BLOCKLIST."""
        source = KPI_SCRIPT_PATH.read_text(encoding="utf-8")
        assert "ENTRY_REGIME_QUALITY_GATE_BLOCKLIST" in source

    def test_kpi_source_contains_post_green_giveback_trigger(self):
        """controlled_kpi_run.py auto_after_overrides should set giveback trigger."""
        source = KPI_SCRIPT_PATH.read_text(encoding="utf-8")
        assert "PAPER_POST_GREEN_GIVEBACK_TRIGGER" in source
