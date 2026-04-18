import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.kucoin_client import KucoinClient, normalize_balances


class DummyResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class DummySession:
    def __init__(self, payload):
        self.payload = payload
        self.last_request = None

    def request(self, method, url, params=None, data=None, headers=None, timeout=None):
        self.last_request = {
            "method": method,
            "url": url,
            "params": params,
            "data": data,
            "headers": headers,
            "timeout": timeout,
        }
        return DummyResponse(self.payload)


def test_kucoin_balance_normalization():
    payload = {
        "code": "200000",
        "data": [
            {
                "type": "trade",
                "currency": "USDT",
                "available": "10",
                "holds": "1",
                "balance": "11",
            }
        ],
    }
    client = KucoinClient(
        api_key="k",
        api_secret="s",
        api_passphrase="p",
        session=DummySession(payload),
    )
    accounts = client.get_accounts()
    normalized = normalize_balances(accounts, timestamp="2025-01-01T00:00:00Z")

    assert isinstance(normalized, list)
    assert normalized[0]["account_type"] == "trade"
    assert normalized[0]["currency"] == "USDT"
    assert normalized[0]["available"] == 10.0
    assert normalized[0]["holds"] == 1.0
    assert normalized[0]["total"] == 11.0
    assert normalized[0]["timestamp"] == "2025-01-01T00:00:00Z"
