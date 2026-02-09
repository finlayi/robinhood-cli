from __future__ import annotations

import base64
import json

import pytest

import rhx.providers.crypto_official as crypto_module
from rhx.errors import CLIError, ErrorCode
from rhx.models import OrderIntentCrypto
from rhx.providers.crypto_official import RobinhoodCryptoProvider


class FakeAuth:
    def __init__(self, api_key: str | None, secret_b64: str | None):
        self._api_key = api_key
        self._secret = secret_b64

    def crypto_credentials(self):
        return self._api_key, self._secret


class FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = "", raw_content: bytes | None = None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        if raw_content is not None:
            self.content = raw_content
        elif payload is None:
            self.content = b""
        else:
            self.content = b"1"

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeClient:
    response: FakeResponse | None = None
    last_request: dict | None = None

    def __init__(self, timeout: float):
        del timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        del exc_type, exc, tb
        return False

    def request(self, method, url, headers=None, json=None, params=None):
        FakeClient.last_request = {
            "method": method,
            "url": url,
            "headers": headers,
            "json": json,
            "params": params,
        }
        assert FakeClient.response is not None
        return FakeClient.response


def make_provider(api_key: str | None = "api"):
    secret = base64.b64encode(b"0" * 32).decode()
    return RobinhoodCryptoProvider(auth=FakeAuth(api_key, secret if api_key else None), base_url="https://example.test")


def test_missing_credentials_raise_auth_required():
    provider = RobinhoodCryptoProvider(auth=FakeAuth(None, None), base_url="https://example.test")
    with pytest.raises(CLIError) as exc:
        provider._credentials()
    assert exc.value.code == ErrorCode.AUTH_REQUIRED


def test_sign_and_request_success(monkeypatch: pytest.MonkeyPatch):
    provider = make_provider()
    monkeypatch.setattr(crypto_module.httpx, "Client", FakeClient)

    FakeClient.response = FakeResponse(200, payload={"ok": True})
    data = provider._request("GET", "/api/v1/crypto/trading/accounts/")

    assert data == {"ok": True}
    assert FakeClient.last_request["headers"]["x-api-key"] == "api"
    assert "x-signature" in FakeClient.last_request["headers"]


def test_request_error_mapping(monkeypatch: pytest.MonkeyPatch):
    provider = make_provider()
    monkeypatch.setattr(crypto_module.httpx, "Client", FakeClient)

    FakeClient.response = FakeResponse(429, payload={"error": "rl"}, text="rate")
    with pytest.raises(CLIError) as rate_exc:
        provider._request("GET", "/x")
    assert rate_exc.value.code == ErrorCode.RATE_LIMITED

    FakeClient.response = FakeResponse(401, payload={"error": "auth"}, text="unauthorized")
    with pytest.raises(CLIError) as auth_exc:
        provider._request("GET", "/x")
    assert auth_exc.value.code == ErrorCode.AUTH_REQUIRED

    FakeClient.response = FakeResponse(500, payload={"error": "server"}, text="server")
    with pytest.raises(CLIError) as broker_exc:
        provider._request("GET", "/x")
    assert broker_exc.value.code == ErrorCode.BROKER_REJECTED


def test_request_non_json_body_falls_back_to_text(monkeypatch: pytest.MonkeyPatch):
    provider = make_provider()
    monkeypatch.setattr(crypto_module.httpx, "Client", FakeClient)

    FakeClient.response = FakeResponse(200, payload=ValueError("bad json"), text="plain", raw_content=b"abc")
    data = provider._request("GET", "/x")
    assert data == {"text": "plain"}


def test_auth_status_success_and_failure(monkeypatch: pytest.MonkeyPatch):
    provider = make_provider()

    monkeypatch.setattr(provider, "_request", lambda method, path: {"ok": True})
    ok = provider.auth_status()
    assert ok.authenticated is True

    def fail(method, path):
        del method, path
        raise CLIError(code=ErrorCode.AUTH_REQUIRED, message="bad")

    monkeypatch.setattr(provider, "_request", fail)
    bad = provider.auth_status()
    assert bad.authenticated is False


def test_high_level_methods_and_place_order_payloads(monkeypatch: pytest.MonkeyPatch):
    provider = make_provider()
    calls = []

    def fake_request(method, path, payload=None, params=None):
        calls.append({"method": method, "path": path, "payload": payload, "params": params})
        if path.endswith("/accounts/"):
            return {"id": "acct"}
        if path.endswith("/holdings/"):
            return {"results": [{"symbol": "BTC-USD"}]}
        if "best_bid_ask" in path:
            return {"bid": "100"}
        if path.endswith("/orders/") and method == "GET":
            return {"results": [{"id": "o1"}]}
        if "/cancel/" in path:
            return {"cancelled": True}
        if "/orders/" in path and method == "POST":
            return {"id": "o123", "state": "queued"}
        return {"id": "single"}

    monkeypatch.setattr(provider, "_request", fake_request)

    assert provider.account_summary()["id"] == "acct"
    assert provider.positions()[0]["symbol"] == "BTC-USD"
    assert provider.quote("BTC-USD")["quote"]["bid"] == "100"

    market_qty = OrderIntentCrypto(symbol="BTC-USD", side="buy", order_type="market", amount_in="quantity", quantity=0.1)
    market_price = OrderIntentCrypto(symbol="BTC-USD", side="buy", order_type="market", amount_in="price", notional_usd=10)
    limit_qty = OrderIntentCrypto(
        symbol="BTC-USD",
        side="sell",
        order_type="limit",
        amount_in="quantity",
        quantity=0.1,
        limit_price=100,
    )
    limit_price = OrderIntentCrypto(
        symbol="BTC-USD",
        side="sell",
        order_type="limit",
        amount_in="price",
        notional_usd=10,
        limit_price=100,
    )

    provider.place_order(market_qty)
    provider.place_order(market_price)
    provider.place_order(limit_qty)
    provider.place_order(limit_price)

    order_payloads = [c["payload"] for c in calls if c["method"] == "POST" and c["path"].endswith("/orders/")]
    assert "market_order_config" in order_payloads[0]
    assert "quote_amount" in order_payloads[1]["market_order_config"]
    assert "asset_quantity" in order_payloads[2]["limit_order_config"]
    assert "quote_amount" in order_payloads[3]["limit_order_config"]

    listed = provider.list_orders(open_only=True)
    assert listed == [{"id": "o1"}]
    assert provider.cancel_order("o1")["result"]["cancelled"] is True
    assert provider.get_order("o1")["order"]["id"] == "single"


def test_place_order_rejects_non_crypto_intent():
    provider = make_provider()
    with pytest.raises(CLIError) as exc:
        provider.place_order(object())
    assert exc.value.code == ErrorCode.VALIDATION_ERROR
