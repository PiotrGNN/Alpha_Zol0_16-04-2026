# kucoin_client.py – minimal KuCoin REST client (public + private)
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


def _clean_secret_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    try:
        v = str(value).strip()
    except Exception:
        return None
    if not v:
        return None
    if v.startswith("\ufeff"):
        v = v.lstrip("\ufeff")
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


def normalize_symbol(symbol: str) -> str:
    """Normalize symbol to KuCoin spot format (e.g., BTC-USDT)."""
    if not symbol:
        return symbol
    return symbol.replace("/", "-").upper()


class KucoinClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        api_passphrase: Optional[str] = None,
        base_url: str = "https://api.kucoin.com",
        timeout: int = 10,
        session: Optional[requests.Session] = None,
    ):
        self.base_url = base_url.rstrip("/")
        if "kucoin.com" not in self.base_url.lower():
            raise ValueError("KucoinClient: non-KuCoin base_url blocked (NO-GO)")
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
                        f"KuCoin HTTP {resp.status_code} code={code} msg={msg}"
                    )
                resp.raise_for_status()
            payload = resp.json()
            if isinstance(payload, dict) and payload.get("code") not in (
                None,
                "200000",
            ):
                raise RuntimeError(
                    f"KuCoin API error code={payload.get('code')} msg={payload.get('msg')}"
                )
            if isinstance(payload, dict) and "data" in payload:
                return payload["data"]
            return payload
        except Exception as exc:
            logging.error(f"KucoinClient request failed: {exc}")
            raise

    def get_market_stats(self, symbol: str) -> Dict[str, Any]:
        return self._request(
            "GET", "/api/v1/market/stats", params={"symbol": normalize_symbol(symbol)}
        )

    def get_level1_orderbook(self, symbol: str) -> Dict[str, Any]:
        return self._request(
            "GET",
            "/api/v1/market/orderbook/level1",
            params={"symbol": normalize_symbol(symbol)},
        )

    def get_level2_orderbook(self, symbol: str, depth: int = 20) -> Dict[str, Any]:
        # KuCoin supports level2_20 and level2_100; keep depth capped.
        depth = 20 if depth <= 20 else 100
        return self._request(
            "GET",
            f"/api/v1/market/orderbook/level2_{depth}",
            params={"symbol": normalize_symbol(symbol)},
        )

    def get_accounts(self, account_type: Optional[str] = None) -> List[Dict[str, Any]]:
        params = {"type": account_type} if account_type else None
        return self._request("GET", "/api/v1/accounts", params=params, private=True)

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
            "symbol": normalize_symbol(symbol),
            "side": side,
            "type": order_type,
        }
        if client_oid:
            body["clientOid"] = client_oid
        if price is not None and order_type != "market":
            body["price"] = price
        if size is not None:
            body["size"] = size
        elif "funds" in kwargs:
            body["funds"] = kwargs["funds"]
        # Pass through any extra order fields (e.g., timeInForce)
        for key, value in kwargs.items():
            if key in body:
                continue
            body[key] = value
        return self._request("POST", "/api/v1/orders", private=True, body=body)


def normalize_balances(
    accounts: List[Dict[str, Any]],
    timestamp: Optional[str] = None,
) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for acct in accounts or []:
        available = acct.get("available") or acct.get("availableBalance") or 0
        holds = acct.get("holds") or acct.get("hold") or 0
        total = acct.get("balance") or acct.get("total") or 0
        account_type = acct.get("type") or acct.get("accountType") or "unknown"
        currency = acct.get("currency") or acct.get("coin") or "unknown"
        try:
            available_f = float(available)
        except Exception:
            available_f = 0.0
        try:
            holds_f = float(holds)
        except Exception:
            holds_f = 0.0
        try:
            total_f = float(total)
        except Exception:
            total_f = available_f + holds_f
        normalized.append(
            {
                "account_type": str(account_type),
                "currency": str(currency),
                "available": available_f,
                "holds": holds_f,
                "total": total_f,
                "timestamp": timestamp,
            }
        )
    return normalized
