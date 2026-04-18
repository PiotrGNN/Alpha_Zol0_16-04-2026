import json
import os
import sys

from security.live_guard import is_live_armed
from core.kucoin_client import KucoinClient
from core.kucoin_futures_client import KucoinFuturesClient, is_futures_symbol


def main() -> int:
    if os.environ.get("LIVE", "0") != "1":
        print("LIVE=0; smoke test expects LIVE=1")
        return 2
    armed, reason = is_live_armed()
    if not armed:
        print(f"LIVE not armed: {reason}")
        return 3

    market_type = os.environ.get("MARKET_TYPE", "").lower()
    symbol = os.environ.get(
        "SMOKE_SYMBOL",
        "BTCUSDTM" if market_type == "futures" else "BTC-USDT",
    )
    try:
        if market_type == "futures" or is_futures_symbol(symbol):
            client = KucoinFuturesClient()
            data = client.get_account_overview(
                currency=os.environ.get("SMOKE_CURRENCY", "USDT")
            )
            print("FUTURES SMOKE OK")
            print(json.dumps(data)[:800])
            return 0
        client = KucoinClient()
        data = client.get_accounts(account_type=os.environ.get("SMOKE_ACCOUNT_TYPE"))
        print("SPOT SMOKE OK")
        print(json.dumps(data)[:800])
        return 0
    except Exception as exc:
        print(f"SMOKE FAIL: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
