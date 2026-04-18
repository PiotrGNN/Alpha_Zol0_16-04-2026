"""
UniversalStrategy.py – Uniwersalny szablon strategii dla ZoL0
"""

from typing import (
    Any,
    Dict,
    List,
    Optional,
)

from strategies.base import Strategy


class UniversalStrategy(Strategy):
    def calculate_position_size(self, signal: dict, account_balance: float) -> float:
        """
        Calculate position size as a fixed fraction
        (e.g., 10%) of account balance.
        Args:
            signal: Trading signal dict (unused in this simple implementation)
            account_balance: Current account balance
        Returns:
            float: Position size
        """
        fraction = self.params.get("risk_fraction", 0.1)
        return float(account_balance) * fraction

    """
    Universal strategy template for ZoL0. Implements robust analyze,
    validate, and to_dict methods for flexible use.
    """

    def __init__(
        self,
        name: str = "UniversalStrategy",
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(name=name)
        self.params: Dict[str, Any] = params or {}
        self.status: str = "ok"
        self.position: Optional[str] = None
        self.last_signal: Optional[str] = None

    def analyze(self, data: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
        """
        Analyze market data and generate trading signals.
        Args:
            data (List[Dict[str, Any]]): List of OHLCV dicts or DataFrame rows.
        Returns:
            Dict[str, Any]: Analysis results with signals and metrics.
        """
        results = {"signals": [], "metrics": {}, "analysis": {}}
        if not data:
            self.last_signal = "wait"
            return results
        last = data[-1]
        open_ = last.get("open", 0)
        close = last.get("close", 0)
        signal = None
        if close > open_:
            signal = {"type": "entry", "side": "buy"}
            self.position = "long"
        elif close < open_:
            signal = {"type": "entry", "side": "sell"}
            self.position = "short"
        else:
            signal = {"type": "wait"}
            self.position = None
        self.last_signal = signal["type"] if isinstance(signal, dict) else signal
        results["signals"].append(signal)
        results["metrics"] = {"open": open_, "close": close}
        if close > open_:
            trend = "up"
        elif close < open_:
            trend = "down"
        else:
            trend = "flat"
        results["analysis"] = {"trend": trend}
        return results

    def validate(self) -> List[str]:
        """
        Validate strategy configuration and parameters.
        Returns:
            List[str]: List of validation error messages.
        """
        errors = []
        # Example: check for required params
        if "risk" in self.params and not (0 < self.params["risk"] <= 1):
            errors.append(f"{self.__class__.__name__}: risk must be in (0, 1]")
        return errors

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize strategy state to a dictionary.
        Returns:
            Dict[str, Any]: State dict.
        """
        return {
            "name": self.__class__.__name__,
            "params": self.params,
            "status": self.status,
            "position": self.position,
            "last_signal": self.last_signal,
        }

    def generate_signal(self, data: List[Dict[str, Any]]) -> str:
        """
        Main method for generating a simple signal (buy/sell/wait/risk_limit).
        Args:
            data (List[Dict[str, Any]]): List of OHLCV dicts or DataFrame rows.
        Returns:
            str: Signal string.
        """
        is_empty = False
        try:
            is_empty = data.empty
        except AttributeError:
            is_empty = not data
        if is_empty:
            self.last_signal = "wait"
            return {"type": "wait"}
        # Example: SMA crossover logic (stub)
        self.last_signal = "buy"
        return {"type": "buy"}

    def restart(self) -> None:
        """Restart the strategy and reset status."""
        self.status = "restarted"
        self.position = None
        self.last_signal = None

    def get_status(self) -> str:
        """Get the current status of the strategy."""
        return self.status
