# MultiChainExecutor.py – egzekutor zleceń na wielu giełdach/CEX/DEX
import logging


class MultiChainExecutor:
    def __init__(self, exchanges):
        invalid = [name for name in exchanges.keys() if str(name).lower() != "kucoin"]
        if invalid:
            raise ValueError("MultiChainExecutor: non-KuCoin exchange blocked (NO-GO)")
        self.exchanges = exchanges

    def select_best_market(self, symbol, side, amount):
        # Przykład: wybierz giełdę z najlepszym spreadem
        best = None
        best_spread = float("inf")
        for name, ex in self.exchanges.items():
            spread = ex.get_spread(symbol)
            if spread < best_spread:
                best_spread = spread
                best = name
        logging.info(f"MultiChainExecutor: best market={best} spread={best_spread}")
        return best

    def execute_order(self, symbol, side, amount):
        market = self.select_best_market(symbol, side, amount)
        if not market:
            logging.warning("MultiChainExecutor: no market available")
            return None
        ex = self.exchanges[market]
        result = ex.execute_order(symbol, side, amount)
        logging.info(f"MultiChainExecutor: order executed on {market}, result={result}")
        return result
