# ProfitAttribution.py – przypisanie zysku/straty do strategii i warunków

import logging

logger = logging.getLogger("ProfitAttribution")


class ProfitAttribution:
    def __init__(self):
        self.attribution = []

    def attribute(self, strategy_id, pnl, market_conditions):
        dna = {
            "strategy_id": strategy_id,
            "pnl": pnl,
            "market": market_conditions,
        }
        self.attribution.append(dna)
        logger.info(
            f"ProfitAttribution: attributed {pnl} to {strategy_id} in "
            f"{market_conditions}"
        )
        return dna

    def summary(self):
        # Podsumowanie DNA zysku
        if not self.attribution:
            return {}
        total_pnl = sum(dna["pnl"] for dna in self.attribution)
        by_strategy = {}
        for dna in self.attribution:
            sid = dna["strategy_id"]
            by_strategy.setdefault(sid, 0)
            by_strategy[sid] += dna["pnl"]
        return {
            "total_pnl": total_pnl,
            "by_strategy": by_strategy,
            "count": len(self.attribution),
        }
