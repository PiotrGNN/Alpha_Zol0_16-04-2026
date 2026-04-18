# ZoL0 LEVEL 0
# ✅ LEVEL-API done: REST, retry, timeout, error logging, throttle, max_retries
# OrderExecutor.py – Mockowa egzekucja zleceń
# ✅ LEVEL-API done: Real KuCoin REST API order execution, error handling,
# retry, throttle

import logging
import math
import time
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from core.kucoin_client import KucoinClient, normalize_symbol
from core.kucoin_futures_client import (
    KucoinFuturesClient,
    is_futures_symbol,
    normalize_futures_symbol,
)


class OrderExecutor:
    """Executor wysyłający zlecenia do KuCoin REST API z obsługą retry,
    throttlingu i logowania."""

    def __init__(
        self,
        api_url="https://api.kucoin.com/api/v1/orders",
        throttle_sec=1,
        max_retries=3,
        api_key=None,
        api_secret=None,
    ):
        import os

        self.api_url = api_url
        if "kucoin.com" not in str(self.api_url).lower():
            raise ValueError("OrderExecutor: non-KuCoin api_url blocked (NO-GO)")
        self.throttle_sec = throttle_sec
        self.max_retries = max_retries
        # Prefer explicit args, else load from env
        self.api_key = api_key or os.environ.get("KUCOIN_API_KEY")
        self.api_secret = api_secret or os.environ.get("KUCOIN_API_SECRET")
        self.last_call = 0
        self._futures_contract_cache = {}
        try:
            self._futures_contract_cache_ttl = int(
                os.environ.get("FUTURES_CONTRACT_CACHE_TTL_SEC", "300")
            )
        except Exception:
            self._futures_contract_cache_ttl = 300

    def _extract_order_id(self, resp: Any) -> Optional[str]:
        if not isinstance(resp, dict):
            return None
        data = resp.get("data") if isinstance(resp.get("data"), dict) else resp
        for key in ("orderId", "order_id", "id"):
            try:
                if data.get(key):
                    return str(data.get(key))
            except Exception:
                continue
        return None

    def _get_fill_items(self, resp: Any) -> List[Dict[str, Any]]:
        if not isinstance(resp, dict):
            return []
        data = resp.get("data") if isinstance(resp.get("data"), dict) else resp
        if isinstance(data, dict):
            items = data.get("items")
            if isinstance(items, list):
                return items
        if isinstance(data, list):
            return data
        return []

    def _summarize_fills(
        self, items: List[Dict[str, Any]]
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        total_size = 0.0
        total_value = 0.0
        fee_total = 0.0
        for item in items or []:
            try:
                price = float(item.get("price"))
            except Exception:
                price = None
            try:
                size = float(item.get("size"))
            except Exception:
                size = None
            if price is not None and size is not None:
                total_size += size
                total_value += price * size
            try:
                fee = item.get("fee")
                if fee is None:
                    fee = item.get("closeFeePay")
                if fee is None:
                    fee = item.get("openFeePay")
                fee_total += float(fee) if fee is not None else 0.0
            except Exception as exc:
                logging.debug(
                    "OrderExecutor: fill fee parse failed item=%s error=%s",
                    item,
                    exc,
                )
        avg_price = (total_value / total_size) if total_size > 0 else None
        return (
            avg_price,
            fee_total if fee_total else None,
            total_size if total_size else None,
        )

    def _as_float(self, value: Any) -> Optional[float]:
        try:
            return float(value)
        except Exception:
            return None

    def _make_client_oid(self, prefix: str = "zol0", max_len: int = 36) -> str:
        uid = uuid.uuid4().hex
        if not prefix:
            return uid[:max_len]
        prefix = str(prefix)
        min_uid_len = 8
        avail = max_len - len(prefix) - 1
        if avail < min_uid_len:
            trim_len = max(1, max_len - min_uid_len - 1)
            prefix = prefix[:trim_len]
            avail = max_len - len(prefix) - 1
        if avail <= 0:
            return uid[:max_len]
        return f"{prefix}-{uid[:avail]}"

    def _normalize_client_oid(
        self, client_oid: Optional[str], max_len: int = 36
    ) -> Optional[str]:
        if not client_oid:
            return None
        try:
            client_oid = str(client_oid)
        except Exception:
            return None
        if len(client_oid) <= max_len:
            return client_oid
        return client_oid[:max_len]

    def _get_futures_contract_meta(
        self, client: KucoinFuturesClient, symbol: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        if not symbol:
            return None
        api_symbol = normalize_futures_symbol(symbol)
        now = time.time()
        cached = self._futures_contract_cache.get(api_symbol)
        if cached:
            try:
                ts = float(cached.get("ts", 0.0))
                if now - ts < self._futures_contract_cache_ttl:
                    return cached.get("data")
            except Exception as exc:
                logging.debug(
                    (
                        "OrderExecutor: invalid futures contract cache entry "
                        "symbol=%s error=%s"
                    ),
                    api_symbol,
                    exc,
                )
        data = None
        try:
            data = client.get_contract(api_symbol)
        except Exception:
            data = None
        if not data:
            try:
                contracts = client.get_contracts()
                if isinstance(contracts, list):
                    for item in contracts:
                        if str(item.get("symbol", "")).upper() == api_symbol:
                            data = item
                            break
            except Exception:
                data = None
        if data:
            self._futures_contract_cache[api_symbol] = {"ts": now, "data": data}
        return data

    def _calc_contract_size(
        self,
        amount_base: float,
        multiplier: float,
        lot_size: float,
        rounding: str = "floor",
    ) -> float:
        if multiplier <= 0:
            return 0.0
        raw = amount_base / multiplier
        lot = lot_size if lot_size and lot_size > 0 else 1.0
        if rounding == "ceil":
            size = math.ceil(raw / lot) * lot
        elif rounding == "round":
            size = round(raw / lot) * lot
        else:
            size = math.floor(raw / lot) * lot
        return float(size)

    def _resolve_order_detail(
        self, client: KucoinFuturesClient, order_id: str
    ) -> Optional[Dict[str, Any]]:
        try:
            return client.get_order(order_id)
        except Exception as e:
            logging.warning(f"Order detail fetch failed: {e}")
            return None

    def _resolve_fills(
        self,
        client: KucoinFuturesClient,
        order_id: str,
        symbol: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        try:
            max_wait_sec = float(os.environ.get("FILL_WAIT_SEC", "2.0"))
        except Exception:
            max_wait_sec = 2.0
        try:
            poll_sec = float(os.environ.get("FILL_POLL_SEC", "0.2"))
        except Exception:
            poll_sec = 0.2
        try:
            page_size = int(os.environ.get("FILL_PAGE_SIZE", "50"))
        except Exception:
            page_size = 50
        deadline = time.time() + max(0.0, max_wait_sec)
        last_items: List[Dict[str, Any]] = []
        while True:
            try:
                resp = client.get_fills(
                    order_id=order_id,
                    symbol=symbol,
                    current_page=1,
                    page_size=page_size,
                )
                items = self._get_fill_items(resp)
                if items:
                    return items
                last_items = items or last_items
            except Exception as e:
                logging.warning(f"Fill fetch failed: {e}")
            if time.time() >= deadline:
                break
            time.sleep(poll_sec)
        return last_items

    def _attach_fills(
        self, client: KucoinFuturesClient, resp: Any, symbol: Optional[str]
    ) -> Any:
        order_id = self._extract_order_id(resp)
        if not order_id:
            return resp
        fills = self._resolve_fills(client, order_id, symbol=symbol)
        fill_price = None
        fee_total = None
        filled_size = None
        if fills:
            fill_price, fee_total, filled_size = self._summarize_fills(fills)
        order_detail = None
        if fill_price is None:
            order_detail = self._resolve_order_detail(client, order_id)
            if isinstance(order_detail, dict):
                try:
                    fill_price = order_detail.get("avgDealPrice") or order_detail.get(
                        "dealPrice"
                    )
                    if fill_price is not None:
                        fill_price = float(fill_price)
                except Exception:
                    fill_price = None
                try:
                    filled_size = order_detail.get("dealSize") or order_detail.get(
                        "filledSize"
                    )
                    if filled_size is not None:
                        filled_size = float(filled_size)
                except Exception as exc:
                    logging.debug(
                        "OrderExecutor: filled_size parse failed order_id=%s error=%s",
                        order_id,
                        exc,
                    )
        if isinstance(resp, dict):
            resp.setdefault("order_id", order_id)
            if fill_price is not None:
                resp["fill_price"] = fill_price
            if fee_total is not None:
                resp["fill_fee"] = fee_total
            if filled_size is not None:
                resp["filled_size"] = filled_size
            if fills:
                resp["fills"] = fills
            if order_detail:
                resp["order_detail"] = order_detail
        return resp

    def execute_order(
        self,
        order,
        use_rest=True,
        max_retries=None,
        throttle_sec=None,
        token=None,
    ):
        # Enforce input validation and authorization for REST calls
        from security.zero_trust import authorize, validate_input, log_event
        from security.live_guard import is_live_armed
        from core.kill_switch import is_active
        import os

        if os.environ.get("LIVE", "0") == "1" and is_active():
            log_event("ORDER_BLOCKED:KILL_SWITCH")
            logging.warning("OrderExecutor: kill-switch active; blocked.")
            return {"error": "killswitch"}
        # Validate payload
        if not validate_input(order if isinstance(order, dict) else {}):
            log_event("ORDER_BLOCKED:INVALID_PAYLOAD")
            logging.warning("OrderExecutor: invalid order payload; blocked.")
            return {"error": "invalid_payload"}
        # Normalize side for KuCoin API ("buy"/"sell")
        side_raw = str(order.get("side", "")).strip().lower()
        if side_raw in ("long",):
            side_raw = "buy"
        elif side_raw in ("short",):
            side_raw = "sell"
        if side_raw not in ("buy", "sell"):
            log_event("ORDER_BLOCKED:INVALID_SIDE")
            logging.warning("OrderExecutor: invalid side; blocked.")
            return {"error": "invalid_side"}
        token = token or os.environ.get("ZOL0_TOKEN")
        if use_rest and not authorize(token):
            log_event("ORDER_BLOCKED:UNAUTHORIZED")
            logging.warning("OrderExecutor: unauthorized attempt to execute order.")
            return {"error": "unauthorized"}
        if use_rest:
            armed, reason = is_live_armed()
            if not armed:
                log_event(f"ORDER_BLOCKED:LIVE_NOT_ARMED:{reason}")
                logging.warning("OrderExecutor: LIVE not armed; blocking REST order.")
                return {"error": "live_not_armed", "reason": reason}
            try:
                symbol = str(order.get("symbol", ""))
            except Exception:
                symbol = ""
            market_type = os.environ.get("MARKET_TYPE", "").lower()
            is_futures_order = market_type == "futures" or is_futures_symbol(symbol)
        # Allow test to inject a mock requests.post
        post_func = getattr(self, "_requests_post", None) or requests.post
        market_type = os.environ.get("MARKET_TYPE", "").lower()
        is_futures_order = market_type == "futures" or is_futures_symbol(
            order.get("symbol", "")
        )
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": side_raw,
            "symbol": order.get("symbol"),
            "price": order.get("price"),
            "amount": order.get("amount"),
            "sl": order.get("sl"),
            "tp": order.get("tp"),
            "market_type": "futures" if is_futures_order else "spot",
        }
        logging.info(f"TRADE: {log_entry}")
        if not use_rest:
            return log_entry
        symbol = order.get("symbol")
        price = order.get("price")
        order_type = order.get("type") or ("limit" if price else "market")
        amount_base = self._as_float(order.get("amount"))
        client_oid = order.get("clientOid") or order.get("client_oid")
        client_oid = self._normalize_client_oid(client_oid)
        if client_oid:
            try:
                order["clientOid"] = client_oid
            except Exception as exc:
                logging.warning(
                    (
                        "OrderExecutor: cannot persist clientOid into order "
                        "payload error=%s"
                    ),
                    exc,
                )
        if is_futures_order and not client_oid:
            client_oid = self._make_client_oid("zol0")
            try:
                order["clientOid"] = client_oid
            except Exception as exc:
                logging.warning(
                    "OrderExecutor: cannot inject generated clientOid error=%s",
                    exc,
                )
        size_for_exchange = amount_base
        contract_multiplier = None
        size_contracts = None
        contract_meta = None
        reduce_only = bool(order.get("reduceOnly"))
        max_contracts = order.get("max_contracts") or os.environ.get(
            "FUTURES_MAX_CONTRACTS_PER_TRADE"
        )
        try:
            if max_contracts is not None:
                max_contracts = float(max_contracts)
        except Exception:
            max_contracts = None
        futures_client = None
        if is_futures_order:
            futures_client = KucoinFuturesClient(
                api_key=self.api_key,
                api_secret=self.api_secret,
            )
        if is_futures_order and amount_base is not None:
            contract_meta = self._get_futures_contract_meta(futures_client, symbol)
            if contract_meta:
                contract_multiplier = (
                    self._as_float(contract_meta.get("multiplier"))
                    or self._as_float(contract_meta.get("contractSize"))
                    or self._as_float(contract_meta.get("value"))
                    or 1.0
                )
                lot_size = (
                    self._as_float(contract_meta.get("lotSize"))
                    or self._as_float(contract_meta.get("lot"))
                    or self._as_float(contract_meta.get("sizeIncrement"))
                    or 1.0
                )
                min_size = (
                    self._as_float(contract_meta.get("minSize"))
                    or self._as_float(contract_meta.get("minOrderSize"))
                    or lot_size
                    or 1.0
                )
                rounding = "round" if reduce_only else "floor"
                size_contracts = self._calc_contract_size(
                    amount_base, contract_multiplier, lot_size, rounding=rounding
                )
                if (
                    not reduce_only
                    and max_contracts is not None
                    and max_contracts > 0
                    and size_contracts is not None
                ):
                    if min_size and max_contracts < min_size:
                        logging.warning(
                            "Max contracts below min size: symbol=%s max=%s min=%s",
                            symbol,
                            max_contracts,
                            min_size,
                        )
                        return {
                            "error": "max_contracts_below_min_size",
                            "symbol": symbol,
                            "min_size": min_size,
                            "max_contracts": max_contracts,
                        }
                    if size_contracts > max_contracts:
                        logging.info(
                            "Capping contracts: symbol=%s size=%s cap=%s",
                            symbol,
                            size_contracts,
                            max_contracts,
                        )
                        size_contracts = float(max_contracts)
                if size_contracts <= 0 or (min_size and size_contracts < min_size):
                    if reduce_only and min_size:
                        size_contracts = float(min_size)
                    else:
                        can_round_up = False
                        try:
                            alloc_usdt = amount_base * float(price)
                            leverage = order.get("leverage") or os.environ.get(
                                "FUTURES_LEVERAGE"
                            )
                            leverage = float(leverage) if leverage is not None else 0.0
                            min_notional = (
                                float(min_size)
                                * float(contract_multiplier)
                                * float(price)
                            )
                            if leverage and leverage > 0:
                                required_margin = min_notional / leverage
                            else:
                                required_margin = min_notional
                            try:
                                margin_factor = float(
                                    os.environ.get("MIN_MARGIN_FACTOR", "1.05")
                                )
                            except Exception:
                                margin_factor = 1.05
                            if alloc_usdt >= required_margin * margin_factor:
                                can_round_up = True
                        except Exception:
                            can_round_up = False
                        if can_round_up and min_size:
                            logging.info(
                                (
                                    "Rounding up to min contract size: "
                                    "symbol=%s size=%s min=%s"
                                ),
                                symbol,
                                size_contracts,
                                min_size,
                            )
                            size_contracts = float(min_size)
                        else:
                            logging.warning(
                                (
                                    "Order size below min contract size: "
                                    "symbol=%s size=%s min=%s"
                                ),
                                symbol,
                                size_contracts,
                                min_size,
                            )
                            return {
                                "error": "min_size",
                                "symbol": symbol,
                                "min_size": min_size,
                                "size": size_contracts,
                            }
                size_for_exchange = size_contracts
        payload = {
            "symbol": symbol,
            "side": side_raw,
            "size": size_for_exchange,
            "price": price,
            "type": order_type,
        }
        headers = {"Content-Type": "application/json"}
        retries = max_retries if max_retries is not None else self.max_retries
        if throttle_sec is not None:
            throttle = throttle_sec
        else:
            throttle = self.throttle_sec
        use_legacy_post = getattr(self, "_requests_post", None) is not None
        for attempt in range(1, retries + 1):
            now = time.time()
            if now - self.last_call < throttle:
                time.sleep(throttle - (now - self.last_call))
            self.last_call = time.time()
            try:
                logging.info(f"REST API attempt {attempt}: {payload}")
                if is_futures_order:
                    create_fn = getattr(self, "_futures_create_order", None)
                    if create_fn:
                        resp = create_fn(
                            symbol=symbol,
                            side=side_raw,
                            size=size_for_exchange,
                            price=price,
                            order_type=order_type,
                            client_oid=client_oid,
                            leverage=order.get("leverage"),
                            reduceOnly=order.get("reduceOnly"),
                        )
                        logging.info(f"REST API success! Response: {resp}")
                        try:
                            resp = self._attach_fills(
                                futures_client
                                or KucoinFuturesClient(
                                    api_key=self.api_key,
                                    api_secret=self.api_secret,
                                ),
                                resp,
                                symbol,
                            )
                        except Exception as e:
                            logging.warning(f"Fill attachment failed: {e}")
                        if isinstance(resp, dict):
                            if contract_multiplier is not None:
                                resp.setdefault(
                                    "contract_multiplier", contract_multiplier
                                )
                            if size_contracts is not None:
                                resp.setdefault("size_contracts", size_contracts)
                            if (
                                resp.get("filled_size") is not None
                                and contract_multiplier
                            ):
                                try:
                                    resp["filled_base"] = float(
                                        resp.get("filled_size")
                                    ) * float(contract_multiplier)
                                except Exception as exc:
                                    logging.debug(
                                        (
                                            "OrderExecutor: filled_base compute "
                                            "failed order_id=%s error=%s"
                                        ),
                                        resp.get("order_id"),
                                        exc,
                                    )
                        return resp
                    client = futures_client or KucoinFuturesClient(
                        api_key=self.api_key,
                        api_secret=self.api_secret,
                    )
                    resp = client.create_order(
                        symbol=symbol,
                        side=side_raw,
                        size=size_for_exchange,
                        price=price,
                        order_type=order_type,
                        client_oid=client_oid,
                        leverage=order.get("leverage"),
                        reduceOnly=order.get("reduceOnly"),
                    )
                    try:
                        resp = self._attach_fills(client, resp, symbol)
                    except Exception as e:
                        logging.warning(f"Fill attachment failed: {e}")
                    if isinstance(resp, dict):
                        if contract_multiplier is not None:
                            resp.setdefault("contract_multiplier", contract_multiplier)
                        if size_contracts is not None:
                            resp.setdefault("size_contracts", size_contracts)
                        if resp.get("filled_size") is not None and contract_multiplier:
                            try:
                                resp["filled_base"] = float(
                                    resp.get("filled_size")
                                ) * float(contract_multiplier)
                            except Exception as exc:
                                logging.debug(
                                    (
                                        "OrderExecutor: filled_base compute failed "
                                        "order_id=%s error=%s"
                                    ),
                                    resp.get("order_id"),
                                    exc,
                                )
                    logging.info(f"REST API success! Response: {resp}")
                    return resp
                if use_legacy_post:
                    resp = post_func(
                        self.api_url,
                        json=payload,
                        headers=headers,
                        timeout=10,
                    )
                    # For test: allow mock to return dict directly
                    if isinstance(resp, dict):
                        logging.info(f"REST API success! Response: {resp}")
                        return resp
                    resp.raise_for_status()
                    resp_json = resp.json()
                    logging.info(f"REST API success! Response: {resp_json}")
                    return resp_json
                client = KucoinClient(
                    api_key=self.api_key,
                    api_secret=self.api_secret,
                )
                spot_symbol = normalize_symbol(symbol)
                resp = client.create_order(
                    symbol=spot_symbol,
                    side=side_raw,
                    size=order.get("amount"),
                    price=price,
                    order_type=order_type,
                )
                logging.info(f"REST API success! Response: {resp}")
                return resp
            except Exception as e:
                logging.warning(f"REST API error: {e}, retrying...")
                time.sleep(self.throttle_sec)
        logging.error(
            f"OrderExecutor: All REST API attempts failed for order: {payload}"
        )
        return None
