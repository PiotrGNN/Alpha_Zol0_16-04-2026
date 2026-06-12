from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_EDGE_AUDIT_REL = "analysis/locked_positive_expectancy_subset_audit_current.json"
DEFAULT_SCORECARD_REL = "analysis/zol0_profitability_audit_scorecard.json"
DEFAULT_MAX_AGE_DAYS = 7
DEFAULT_MIN_TRADES = 60
DEFAULT_MIN_PROFIT_FACTOR = 1.15
CONTAMINATION_FIELDS = (
    "mock_entry_trade_count",
    "forced_entry_trade_count",
    "fallback_entry_trade_count",
    "seed_entry_trade_count",
    "assisted_entry_trade_count",
    "unknown_entry_trade_count",
)


@dataclass(frozen=True)
class ProfitabilityGateDecision:
    allowed: bool
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off", ""}:
        return False
    return default


def _as_float(value: Any, default: float | None = None) -> float | None:
    if value == "Infinity":
        return math.inf
    try:
        if value is None or isinstance(value, bool):
            return default
        result = float(value)
        if math.isnan(result):
            return default
        return result
    except Exception:
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or isinstance(value, bool):
            return default
        return int(value)
    except Exception:
        return default


def _normalize_symbol(symbol: Any) -> str:
    return str(symbol or "").upper().replace("-", "").replace("/", "").strip()


def _normalize_strategy(strategy: Any) -> str:
    text = str(strategy or "Universal").strip()
    return text.upper() if text else "UNIVERSAL"


def _normalize_side(side: Any) -> str:
    text = str(side or "").strip().lower()
    if text in {"long", "buy"}:
        return "buy"
    if text in {"short", "sell"}:
        return "sell"
    return text


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _fresh_enough(generated_at: Any, max_age_days: int) -> tuple[bool, str]:
    generated = _parse_timestamp(generated_at)
    if generated is None:
        return False, "edge_timestamp_invalid"
    age = datetime.now(timezone.utc) - generated
    if age > timedelta(days=max_age_days):
        return False, "edge_artifact_stale"
    return True, "edge_artifact_fresh"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _resolve_path(raw: str | Path | None, default_rel: str) -> Path:
    text = str(raw or "").strip()
    path = Path(text) if text else _project_root() / default_rel
    if not path.is_absolute():
        path = _project_root() / path
    return path.resolve()


def _contaminated_count(contract: dict[str, Any]) -> int:
    total = sum(_as_int(contract.get(field), 0) for field in CONTAMINATION_FIELDS)
    truth_counts = contract.get("truth_classification_counts")
    if isinstance(truth_counts, dict):
        for key in (
            "PAPER_AUTO_OPEN_FALLBACK",
            "BOOTSTRAP_ALLOWLIST_ASSISTED",
            "SEED_TRADES_OVERRIDE_ASSISTED",
            "UNKNOWN_REQUIRES_REVIEW",
            "MOCK_ENTRY",
            "FORCED_ENTRY",
        ):
            total += _as_int(truth_counts.get(key), 0)
    return total


def _edge_key(symbol: Any, strategy: Any, side: Any) -> str:
    return f"{_normalize_symbol(symbol)}:{_normalize_strategy(strategy)}:{_normalize_side(side)}"


class EdgeProfitabilityGate:
    """
    Fail-closed runtime entry gate.

    It allows a new entry only when a fresh exact-corpus edge artifact confirms
    a positive, full-cost symbol/strategy/side bucket. Missing evidence means
    no trade, not a fallback trade.
    """

    def __init__(
        self,
        *,
        edge_audit_path: str | Path | None = None,
        scorecard_path: str | Path | None = None,
        enabled: bool | None = None,
        max_age_days: int | None = None,
        min_trades: int | None = None,
        min_profit_factor: float | None = None,
    ) -> None:
        self.edge_audit_path = _resolve_path(
            edge_audit_path or os.environ.get("ZOL0_EDGE_AUDIT_PATH"),
            DEFAULT_EDGE_AUDIT_REL,
        )
        self.scorecard_path = _resolve_path(
            scorecard_path or os.environ.get("ZOL0_EDGE_SCORECARD_PATH"),
            DEFAULT_SCORECARD_REL,
        )
        self.enabled = (
            _env_flag("ZOL0_PROFITABILITY_GATE_ENABLED", True)
            if enabled is None
            else bool(enabled)
        )
        self.max_age_days = max(
            1,
            int(
                max_age_days
                if max_age_days is not None
                else os.environ.get("ZOL0_PROFITABILITY_GATE_MAX_AGE_DAYS", DEFAULT_MAX_AGE_DAYS)
            ),
        )
        self.min_trades = max(
            1,
            int(
                min_trades
                if min_trades is not None
                else os.environ.get("ZOL0_PROFITABILITY_GATE_MIN_TRADES", DEFAULT_MIN_TRADES)
            ),
        )
        self.min_profit_factor = float(
            min_profit_factor
            if min_profit_factor is not None
            else os.environ.get(
                "ZOL0_PROFITABILITY_GATE_MIN_PROFIT_FACTOR",
                DEFAULT_MIN_PROFIT_FACTOR,
            )
        )

    def should_trade(
        self,
        *,
        symbol: str,
        strategy: str | None,
        side: str,
    ) -> ProfitabilityGateDecision:
        if not self.enabled:
            return ProfitabilityGateDecision(
                allowed=True,
                reason="profitability_gate_disabled",
                details={"fail_closed": False},
            )

        edge_audit = _load_json(self.edge_audit_path)
        if edge_audit is not None:
            return self._from_locked_positive_subset(edge_audit, symbol, strategy, side)

        scorecard = _load_json(self.scorecard_path)
        if scorecard is not None:
            return self._from_scorecard(scorecard, symbol, strategy, side)

        return ProfitabilityGateDecision(
            allowed=False,
            reason="edge_artifact_missing",
            details={
                "edge_audit_path": str(self.edge_audit_path),
                "scorecard_path": str(self.scorecard_path),
                "fail_closed": True,
            },
        )

    def _from_locked_positive_subset(
        self,
        audit: dict[str, Any],
        symbol: str,
        strategy: str | None,
        side: str,
    ) -> ProfitabilityGateDecision:
        metadata = audit.get("metadata") if isinstance(audit.get("metadata"), dict) else {}
        generated_ok, generated_reason = _fresh_enough(
            metadata.get("generated_at"),
            self.max_age_days,
        )
        if not generated_ok:
            return ProfitabilityGateDecision(False, generated_reason, {"source": "locked_positive_subset"})

        evidence = audit.get("evidence_contract") if isinstance(audit.get("evidence_contract"), dict) else {}
        decision = audit.get("subset_decision") if isinstance(audit.get("subset_decision"), dict) else {}
        if evidence.get("status") != "PASS":
            return ProfitabilityGateDecision(False, "edge_evidence_contract_not_pass", {"status": evidence.get("status")})
        if decision.get("status") != "PASS":
            return ProfitabilityGateDecision(False, "positive_subset_not_found", {"status": decision.get("status")})
        if decision.get("fallback_allowed") is not False:
            return ProfitabilityGateDecision(False, "fallback_not_allowed_contract_missing", {"fallback_allowed": decision.get("fallback_allowed")})

        key = _edge_key(symbol, strategy, side)
        allowlist = {
            str(item or "").upper().replace("-", "").replace("/", "").strip()
            for item in decision.get("locked_symbol_strategy_side_allowlist") or []
        }
        if key not in allowlist:
            return ProfitabilityGateDecision(
                False,
                "symbol_strategy_side_not_in_positive_allowlist",
                {"key": key, "allowlist_size": len(allowlist)},
            )

        row = self._find_ranking_row(audit, symbol, strategy, side)
        if row is None:
            return ProfitabilityGateDecision(False, "positive_bucket_metrics_missing", {"key": key})

        return self._evaluate_bucket(row, source="locked_positive_subset", key=key)

    def _find_ranking_row(
        self,
        audit: dict[str, Any],
        symbol: str,
        strategy: str | None,
        side: str,
    ) -> dict[str, Any] | None:
        rankings = audit.get("rankings") if isinstance(audit.get("rankings"), dict) else {}
        rows = rankings.get("symbol_strategy_side") or []
        expected = _edge_key(symbol, strategy, side)
        for row in rows:
            if not isinstance(row, dict):
                continue
            actual = _edge_key(row.get("symbol"), row.get("strategy"), row.get("side"))
            if actual == expected:
                return row
        return None

    def _evaluate_bucket(
        self,
        row: dict[str, Any],
        *,
        source: str,
        key: str,
    ) -> ProfitabilityGateDecision:
        trade_count = _as_int(
            row.get("natural_entry_trade_count", row.get("trade_count")),
            0,
        )
        expectancy = _as_float(row.get("expectancy", row.get("avg_pnl_per_trade")), None)
        net_pnl = _as_float(row.get("net_pnl"), None)
        profit_factor = _as_float(row.get("profit_factor"), None)
        selected = row.get("selected")

        details = {
            "source": source,
            "key": key,
            "trade_count": trade_count,
            "min_trades": self.min_trades,
            "expectancy": expectancy,
            "net_pnl": net_pnl,
            "profit_factor": profit_factor,
            "min_profit_factor": self.min_profit_factor,
            "selected": selected,
        }
        if selected is False:
            return ProfitabilityGateDecision(False, "positive_bucket_not_selected", details)
        if trade_count < self.min_trades:
            return ProfitabilityGateDecision(False, "natural_trade_sample_too_small", details)
        if expectancy is None or expectancy <= 0:
            return ProfitabilityGateDecision(False, "expectancy_not_positive", details)
        if net_pnl is not None and net_pnl <= 0:
            return ProfitabilityGateDecision(False, "net_pnl_not_positive", details)
        if profit_factor is None or profit_factor < self.min_profit_factor:
            return ProfitabilityGateDecision(False, "profit_factor_below_runtime_min", details)
        return ProfitabilityGateDecision(True, "edge_confirmed", details)

    def _from_scorecard(
        self,
        scorecard: dict[str, Any],
        symbol: str,
        strategy: str | None,
        side: str,
    ) -> ProfitabilityGateDecision:
        metadata = scorecard.get("metadata") if isinstance(scorecard.get("metadata"), dict) else {}
        generated_ok, generated_reason = _fresh_enough(
            metadata.get("generated_at"),
            self.max_age_days,
        )
        if not generated_ok:
            return ProfitabilityGateDecision(False, generated_reason, {"source": "scorecard"})

        scope = metadata.get("scope") if isinstance(metadata.get("scope"), dict) else {}
        validation = metadata.get("validation") if isinstance(metadata.get("validation"), dict) else {}
        if str(scope.get("exchange") or "").lower() != "kucoin":
            return ProfitabilityGateDecision(False, "scorecard_scope_not_kucoin", {"scope": scope})
        if str(scope.get("mode") or "").upper() != "PAPER_ONLY" or scope.get("live_in_scope") is not False:
            return ProfitabilityGateDecision(False, "scorecard_scope_not_paper_only", {"scope": scope})
        if validation.get("all_passed") is not True:
            return ProfitabilityGateDecision(False, "scorecard_validation_not_passed", {"validation": validation})

        row = self._find_scorecard_row(scorecard, symbol, strategy, side)
        if row is not None:
            return self._evaluate_bucket(
                row,
                source="scorecard_bucket",
                key=_edge_key(symbol, strategy, side),
            )

        return self._evaluate_global_scorecard(scorecard, symbol, strategy, side)

    def _find_scorecard_row(
        self,
        scorecard: dict[str, Any],
        symbol: str,
        strategy: str | None,
        side: str,
    ) -> dict[str, Any] | None:
        expected = _edge_key(symbol, strategy, side)
        candidate_containers = (
            scorecard.get("cohorts"),
            scorecard.get("selected_cohorts"),
            scorecard.get("positive_cohorts"),
            scorecard.get("symbol_strategy_side"),
            (scorecard.get("rankings") or {}).get("symbol_strategy_side")
            if isinstance(scorecard.get("rankings"), dict)
            else None,
        )
        for container in candidate_containers:
            if not isinstance(container, list):
                continue
            for row in container:
                if not isinstance(row, dict):
                    continue
                actual = _edge_key(row.get("symbol"), row.get("strategy"), row.get("side"))
                if actual == expected:
                    return row
        return None

    def _evaluate_global_scorecard(
        self,
        scorecard: dict[str, Any],
        symbol: str,
        strategy: str | None,
        side: str,
    ) -> ProfitabilityGateDecision:
        kpis = scorecard.get("global_kpis") if isinstance(scorecard.get("global_kpis"), dict) else {}
        contract = (
            kpis.get("strategy_validation_contract")
            if isinstance(kpis.get("strategy_validation_contract"), dict)
            else {}
        )
        natural = (
            kpis.get("natural_entry_metrics")
            if isinstance(kpis.get("natural_entry_metrics"), dict)
            else {}
        )
        contamination = _contaminated_count(contract)
        details = {
            "source": "scorecard_global",
            "key": _edge_key(symbol, strategy, side),
            "usable_strategy_economics": contract.get("usable_strategy_economics"),
            "natural_entry_trade_count": _as_int(contract.get("natural_entry_trade_count"), 0),
            "contamination_count": contamination,
            "expectancy": _as_float(natural.get("expectancy"), None),
            "profit_factor": _as_float(natural.get("profit_factor"), None),
            "note": "global scorecard is not an exact symbol/strategy/side approval",
        }
        if os.environ.get("ZOL0_PROFITABILITY_GATE_ALLOW_GLOBAL", "0") != "1":
            return ProfitabilityGateDecision(False, "exact_edge_bucket_missing", details)
        if contract.get("usable_strategy_economics") is not True:
            return ProfitabilityGateDecision(False, "strategy_economics_not_usable", details)
        if contamination > 0:
            return ProfitabilityGateDecision(False, "corpus_contaminated", details)
        if details["natural_entry_trade_count"] < self.min_trades:
            return ProfitabilityGateDecision(False, "natural_trade_sample_too_small", details)
        if details["expectancy"] is None or details["expectancy"] <= 0:
            return ProfitabilityGateDecision(False, "expectancy_not_positive", details)
        if details["profit_factor"] is None or details["profit_factor"] < self.min_profit_factor:
            return ProfitabilityGateDecision(False, "profit_factor_below_runtime_min", details)
        return ProfitabilityGateDecision(True, "global_edge_confirmed", details)
