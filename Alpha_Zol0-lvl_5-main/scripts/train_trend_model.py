import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import pandas as pd

from utils.config_loader import load_config
from core.MarketDataFetcher import MarketDataFetcher
from core.kucoin_futures_client import (
    is_futures_symbol,
    normalize_futures_symbol,
)
from models.trend_predictor import TrendPredictor


def main() -> int:
    config = load_config("config/config.yaml")
    symbols = config.get("symbols") or [config.get("symbol", "BTCUSDTM")]
    symbol = symbols[0]
    if symbol is None:
        print("No symbol configured.", file=sys.stderr)
        return 1
    symbol = str(symbol)
    if is_futures_symbol(symbol):
        symbol = normalize_futures_symbol(symbol)

    try:
        ohlcv_limit = int(os.environ.get("TREND_TRAIN_OHLCV_LIMIT", "500"))
    except Exception:
        ohlcv_limit = 500
    timeframe = str(config.get("timeframe", "1"))
    market_type = os.environ.get("MARKET_TYPE", "futures")
    api_url = config.get("api_url", "https://api.kucoin.com/api/v1/market/candles")
    fetcher = MarketDataFetcher(api_url=api_url, market_type=market_type)

    candles = fetcher.get_ohlcv(symbol, timeframe, limit=ohlcv_limit)
    if not candles:
        print("No OHLCV data fetched.", file=sys.stderr)
        return 1
    df = pd.DataFrame(candles)
    if df.empty:
        print("OHLCV DataFrame is empty.", file=sys.stderr)
        return 1

    predictor = TrendPredictor(model_path="trend_model.pkl")
    predictor.fit(df)
    if not predictor.is_trained:
        print("TrendPredictor training failed.", file=sys.stderr)
        return 1
    print(f"trend_model.pkl saved in {os.getcwd()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
