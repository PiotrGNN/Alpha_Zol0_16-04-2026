# zero_drawdown_guard.py – Wykrycie/stop drawdownu

from typing import List


class ZeroDrawdownGuard:
    """
    Guard to detect and stop trading if drawdown exceeds a
    specified threshold.
    """

    def check(
        self,
        equity_curve: List[float],
        max_drawdown: float = 0.2,
    ) -> bool:
        """
        Return False when the worst peak-to-trough drawdown exceeds the limit.
        """
        try:
            values = [float(value) for value in equity_curve]
        except Exception:
            return False
        if not values:
            return True
        try:
            limit = float(max_drawdown)
        except Exception:
            return False
        if limit < 0.0:
            return False

        peak = values[0]
        worst_drawdown = 0.0
        for value in values:
            if value < 0.0:
                return False
            if value > peak:
                peak = value
                continue
            if peak <= 0.0:
                continue
            drawdown = (peak - value) / peak
            if drawdown > worst_drawdown:
                worst_drawdown = drawdown
                if worst_drawdown > limit:
                    return False
        return True
