# kucoin_futures_client.py – KuCoin Futures REST (market + trading)
import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests
from utils.time import to_ms

# Futures REST base URL per KuCoin docs:
# https://www.kucoin.com/docs/rest/futures-trading/market-data/get-klines
FUTURES_BASE_URL = "https://api-futures.kucoin.com"

# Endpoints per KuCoin Futures docs:
# Ticker: https://www.kucoin.com/docs-new/rest/futures-trading/market-data/get-ticker
# Klines: https://www.kucoin.com/docs-new/rest/futures-trading/market-data/get-klines
# Account overview (futures):
# https://www.kucoin.com/docs-new/rest/account-info/account-funding/get-account-futures
TICKER_PATH = "/api/v1/ticker"
ALL_TICKERS_PATH = "/api/v1/allTickers"
KLINES_PATH = "/api/v1/kline/query"
ACCOUNT_OVERVIEW_PATH = "/api/v1/account-overview"
ORDER_PATH = "/api/v1/orders"
ORDER_DETAIL_PATH = "/api/v1/orders/{orderId}"
FILLS_PATH = "/api/v1/fills"
POSITION_PATH = "/api/v1/position"
CONTRACTS_PATH = "/api/v1/contracts/active"
CONTRACT_DETAIL_PATH = "/api/v1/contracts/{symbol}"


def is_futures_symbol(symbol: str) -> bool:
    return bool(symbol) and symbol.upper().endswith("USDTM")


# KuCoin Futures contract aliases (external symbol -> KuCoin contract symbol)
# KuCoin uses XBT for BTC perpetual.
FUTURES_SYMBOL_ALIASES = {
    "BTCUSDTM": "XBTUSDTM",
}


def normalize_futures_symbol(symbol: str) -> str:
    if not symbol:
        return symbol
    upper = symbol.upper()
    return FUTURES_SYMBOL_ALIASES.get(upper, upper)


def _clean_secret_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    try:
        v = str(value).strip()
    except Exception:
        return None
    if not v:
        return None
    # Strip UTF-8 BOM if present
    if v.startswith("\ufeff"):
        v = v.lstrip("\ufeff")
    # Strip surrounding quotes if present
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        v = v[1:-1].strip()
    return v or None


def _read_secret_file(path: Optional[str]) -> Optional[str]:
    try:
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return _clean_secret_value(f.read())
    except Exception:
        return None
    return None


def interval_to_granularity(interval: str) -> int:
    """
    Convert interval string to KuCoin Futures granularity (minutes).
    KuCoin Futures expects granularity in MINUTES (1,5,15,30,60,120,...).
    Examples: "1min"->1, "5min"->5, "1hour"->60.
    """
    if interval is None:
        return 1
    interval_str = str(interval).lower().strip()
    if interval_str.isdigit():
        return int(interval_str)
    mapping = {
        "1min": 1,
        "3min": 3,
        "5min": 5,
        "15min": 15,
        "30min": 30,
        "1hour": 60,
        "2hour": 120,
        "4hour": 240,
        "8hour": 480,
        "12hour": 720,
        "1day": 1440,
        "1week": 10080,
        "1month": 43200,
    }
    return mapping.get(interval_str, 1)


class KucoinFuturesClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        api_passphrase: Optional[str] = None,
        base_url: str = FUTURES_BASE_URL,
        timeout: int = 10,
        session: Optional[requests.Session] = None,
    ):
        self.base_url = base_url.rstrip("/")
        if "kucoin.com" not in self.base_url.lower():
            raise ValueError("KucoinFuturesClient: non-KuCoin base_url blocked (NO-GO)")
        self.api_key = (
            _clean_secret_value(api_key)
            or _clean_secret_value(os.getenv("KUCOIN_API_KEY"))
            or _read_secret_file(
                os.getenv("KUCOIN_API_KEY_FILE") or "/run/secrets/KUCOIN_API_KEY"
            )
        )
        self.api_secret = (
            _clean_secret_value(api_secret)
            or _clean_secret_value(os.getenv("KUCOIN_API_SECRET"))
            or _read_secret_file(
                os.getenv("KUCOIN_API_SECRET_FILE") or "/run/secrets/KUCOIN_API_SECRET"
            )
        )
        self.api_passphrase = (
            _clean_secret_value(api_passphrase)
            or _clean_secret_value(os.getenv("KUCOIN_API_PASSPHRASE"))
            or _clean_secret_value(os.getenv("KUCOIN_PASSPHRASE"))
            or _read_secret_file(
                os.getenv("KUCOIN_API_PASSPHRASE_FILE")
                or os.getenv("KUCOIN_PASSPHRASE_FILE")
                or "/run/secrets/KUCOIN_PASSPHRASE"
            )
        )
        self.timeout = timeout
        self._session = session or requests.Session()

    def _timestamp(self) -> str:
        return str(int(time.time() * 1000))

    def _sign_headers(
        self,
        method: str,
        request_path: str,
        query: Optional[Dict[str, Any]] = None,
        body: Optional[str] = "",
        key_version: Optional[str] = None,
        force_plain_passphrase: bool = False,
    ) -> Dict[str, str]:
        if not self.api_key or not self.api_secret or not self.api_passphrase:
            raise ValueError("KuCoin credentials missing (key/secret/passphrase)")
        query_str = urlencode(query or {}, doseq=True)
        path = request_path + (f"?{query_str}" if query_str else "")
        timestamp = self._timestamp()
        prehash = f"{timestamp}{method.upper()}{path}{body or ''}"
        sign = base64.b64encode(
            hmac.new(
                self.api_secret.encode("utf-8"),
                prehash.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode("utf-8")
        version = str(key_version or os.getenv("KUCOIN_API_KEY_VERSION") or "2").strip()
        version_norm = version.lower().replace("v", "")
        use_v2 = (version_norm == "2") and not force_plain_passphrase
        if use_v2:
            passphrase = base64.b64encode(
                hmac.new(
                    self.api_secret.encode("utf-8"),
                    self.api_passphrase.encode("utf-8"),
                    hashlib.sha256,
                ).digest()
            ).decode("utf-8")
        else:
            passphrase = self.api_passphrase
        headers = {
            "KC-API-KEY": self.api_key,
            "KC-API-SIGN": sign,
            "KC-API-TIMESTAMP": timestamp,
            "KC-API-PASSPHRASE": passphrase,
            "Content-Type": "application/json",
        }
        if use_v2:
            headers["KC-API-KEY-VERSION"] = "2"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        private: bool = False,
        body: Optional[Dict[str, Any]] = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        body_json = json.dumps(body) if body else ""
        headers: Dict[str, str] = {}
        key_version = os.getenv("KUCOIN_API_KEY_VERSION") or "2"
        if private:
            headers = self._sign_headers(
                method, path, params, body_json, key_version=key_version
            )
        try:
            resp = self._session.request(
                method=method.upper(),
                url=url,
                params=params if method.upper() == "GET" else None,
                data=body_json if body_json else None,
                headers=headers,
                timeout=self.timeout,
            )
            status_code = getattr(resp, "status_code", None)
            if private and status_code == 401:
                version_norm = str(key_version).lower().replace("v", "")
                if version_norm != "1":
                    headers = self._sign_headers(
                        method,
                        path,
                        params,
                        body_json,
                        key_version="1",
                        force_plain_passphrase=True,
                    )
                    resp = self._session.request(
                        method=method.upper(),
                        url=url,
                        params=params if method.upper() == "GET" else None,
                        data=body_json if body_json else None,
                        headers=headers,
                        timeout=self.timeout,
                    )
            if getattr(resp, "status_code", 0) >= 400:
                err_payload = {}
                try:
                    err_payload = resp.json()
                except Exception:
                    err_payload = {}
                code = None
                msg = None
                if isinstance(err_payload, dict):
                    code = err_payload.get("code")
                    msg = err_payload.get("msg") or err_payload.get("message")
                if code or msg:
                    raise RuntimeError(
                        f"KuCoin Futures HTTP {resp.status_code} code={code} msg={msg}"
                    )
                resp.raise_for_status()
            payload = resp.json()
            if isinstance(payload, dict) and payload.get("code") not in (
                None,
                "200000",
            ):
                raise RuntimeError(
                    "KuCoin Futures API error "
                    f"code={payload.get('code')} msg={payload.get('msg')}"
                )
            if isinstance(payload, dict) and "data" in payload:
                return payload["data"]
            return payload
        except Exception as exc:
            logging.error(f"KucoinFuturesClient request failed: {exc}")
            raise

    def get_ticker(self, symbol: str) -> Dict[str, Any]:
        api_symbol = normalize_futures_symbol(symbol)
        return self._request("GET", TICKER_PATH, params={"symbol": api_symbol})

    def get_all_tickers(self) -> List[Dict[str, Any]]:
        data = self._request("GET", ALL_TICKERS_PATH)
        return data if isinstance(data, list) else []

    def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 200,
        end_ms: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        api_symbol = normalize_futures_symbol(symbol)
        granularity = interval_to_granularity(interval)
        end_ms = end_ms or int(time.time() * 1000)
        start_ms = end_ms - (limit * granularity * 60 * 1000)
        params = {
            "symbol": api_symbol,
            "granularity": granularity,
            "from": start_ms,
            "to": end_ms,
        }
        data = self._request("GET", KLINES_PATH, params=params)
        candles: List[Dict[str, Any]] = []
        # Field order per KuCoin Futures Klines REST docs:
        # https://www.kucoin.com/docs-new/rest/futures-trading/market-data/get-klines
        # Example array: [time, open, high, low, close, volume, turnover]
        for item in data or []:
            if not item or len(item) < 7:
                continue
            candles.append(
                {
                    "timestamp": to_ms(item[0]),
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5]),
                    "turnover": float(item[6]),
                }
            )
        return candles

    def get_account_overview(self, currency: str = "USDT") -> Dict[str, Any]:
        params = {"currency": currency} if currency else None
        return self._request("GET", ACCOUNT_OVERVIEW_PATH, params=params, private=True)

    def get_position(self, symbol: str) -> Dict[str, Any]:
        if not symbol:
            raise ValueError("symbol is required")
        api_symbol = normalize_futures_symbol(symbol)
        return self._request(
            "GET", POSITION_PATH, params={"symbol": api_symbol}, private=True
        )

    def get_order(self, order_id: str) -> Dict[str, Any]:
        if not order_id:
            raise ValueError("order_id is required")
        path = ORDER_DETAIL_PATH.format(orderId=order_id)
        return self._request("GET", path, private=True)

    def get_contracts(self) -> List[Dict[str, Any]]:
        return self._request("GET", CONTRACTS_PATH)

    def get_contract(self, symbol: str) -> Dict[str, Any]:
        if not symbol:
            raise ValueError("symbol is required")
        api_symbol = normalize_futures_symbol(symbol)
        path = CONTRACT_DETAIL_PATH.format(symbol=api_symbol)
        return self._request("GET", path)

    def get_fills(
        self,
        order_id: Optional[str] = None,
        symbol: Optional[str] = None,
        start_at: Optional[int] = None,
        end_at: Optional[int] = None,
        current_page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "currentPage": current_page,
            "pageSize": page_size,
        }
        if order_id:
            params["orderId"] = order_id
        if symbol:
            params["symbol"] = normalize_futures_symbol(symbol)
        if start_at:
            params["startAt"] = int(start_at)
        if end_at:
            params["endAt"] = int(end_at)
        return self._request("GET", FILLS_PATH, params=params, private=True)

    def create_order(
        self,
        symbol: str,
        side: str,
        size: Optional[float] = None,
        price: Optional[float] = None,
        order_type: str = "limit",
        client_oid: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "symbol": normalize_futures_symbol(symbol),
            "side": side,
            "type": order_type,
        }
        if client_oid:
            body["clientOid"] = client_oid
        if price is not None and order_type != "market":
            body["price"] = price
        if size is not None:
            body["size"] = size
        # Pass through any extra futures fields (leverage, reduceOnly, etc.)
        for key, value in kwargs.items():
            if key in body:
                continue
            body[key] = value
        return self._request("POST", ORDER_PATH, private=True, body=body)
