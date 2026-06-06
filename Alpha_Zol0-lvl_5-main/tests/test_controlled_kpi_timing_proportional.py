"""Tests for Faza 2A/2B: proportional ENTRY_CUTOFF_BEFORE_END_SEC and
PAPER_AUTO_CLOSE_HARD_SEC values in the auto_after_overrides dict.

These formulas are embedded in the auto_after_overrides dict inside main(),
so we verify them by evaluating the same expressions directly.
"""


def _cutoff_sec(after_min: int) -> int:
    """Mirrors: min(180, max(60, (args.after_min * 60 * 25) // 100))"""
    return min(180, max(60, (after_min * 60 * 25) // 100))


def _auto_close_hard_sec(after_min: int, paper_auto_close_sec: int) -> int:
    """Mirrors: max((after_min*60*40)//100, paper_auto_close_sec*2, 300)"""
    return max(
        (after_min * 60 * 40) // 100,
        paper_auto_close_sec * 2,
        300,
    )


# ------------------------------------------------------------------ #
# ENTRY_CUTOFF_BEFORE_END_SEC
# ------------------------------------------------------------------ #

class TestCutoffFormula:
    def test_very_short_window_clamps_to_60(self):
        # after_min=1 → (1*60*25)//100 = 15 → clamped to 60
        assert _cutoff_sec(1) == 60

    def test_6min_window(self):
        # after_min=6 → (6*60*25)//100 = 90 → within [60,180]
        assert _cutoff_sec(6) == 90

    def test_10min_window(self):
        # after_min=10 → (10*60*25)//100 = 150 → within [60,180]
        assert _cutoff_sec(10) == 150

    def test_15min_clamps_to_180(self):
        # after_min=15 → (15*60*25)//100 = 225 → clamped to 180
        assert _cutoff_sec(15) == 180

    def test_30min_still_clamps_to_180(self):
        assert _cutoff_sec(30) == 180

    def test_result_always_at_least_60(self):
        for after_min in range(1, 31):
            assert _cutoff_sec(after_min) >= 60

    def test_result_never_exceeds_180(self):
        for after_min in range(1, 61):
            assert _cutoff_sec(after_min) <= 180

    def test_monotonically_increasing_up_to_cap(self):
        prev = _cutoff_sec(1)
        for after_min in range(2, 20):
            cur = _cutoff_sec(after_min)
            assert cur >= prev, f"Expected monotone at after_min={after_min}"
            prev = cur


# ------------------------------------------------------------------ #
# PAPER_AUTO_CLOSE_HARD_SEC
# ------------------------------------------------------------------ #

class TestAutoCloseHardFormula:
    def test_minimum_floor_300(self):
        # Very short window, small paper_auto_close_sec → clamped to 300
        assert _auto_close_hard_sec(after_min=1, paper_auto_close_sec=60) == 300

    def test_6min_default_close_sec_240(self):
        # after_min=6 → (6*60*40)//100 = 144, paper_auto_close_sec=240 → 2*240=480
        # max(144, 480, 300) = 480
        assert _auto_close_hard_sec(6, 240) == 480

    def test_15min_window(self):
        # after_min=15 → (15*60*40)//100 = 360, 2*240=480 → max(360,480,300)=480
        assert _auto_close_hard_sec(15, 240) == 480

    def test_30min_window_dominant(self):
        # after_min=30 → (30*60*40)//100 = 720, 2*240=480 → max(720,480,300)=720
        assert _auto_close_hard_sec(30, 240) == 720

    def test_always_at_least_300(self):
        for after_min in range(1, 31):
            val = _auto_close_hard_sec(after_min, 120)
            assert val >= 300, f"Expected >= 300 at after_min={after_min}"

    def test_always_at_least_twice_paper_close_sec(self):
        for paper_auto_close_sec in [60, 120, 240, 480]:
            for after_min in range(1, 31):
                val = _auto_close_hard_sec(after_min, paper_auto_close_sec)
                assert val >= paper_auto_close_sec * 2, (
                    f"Expected >= 2x paper_auto_close_sec={paper_auto_close_sec}"
                )

    def test_proportional_growth_with_after_min(self):
        prev = _auto_close_hard_sec(1, 60)
        for after_min in range(2, 31):
            cur = _auto_close_hard_sec(after_min, 60)
            assert cur >= prev, (
                f"Expected monotone at after_min={after_min}: {cur} < {prev}"
            )
            prev = cur
