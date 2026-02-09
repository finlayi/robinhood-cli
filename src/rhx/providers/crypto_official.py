from __future__ import annotations

import base64
import json
import time
import uuid
from typing import Any

import httpx
from nacl.signing import SigningKey

from rhx.auth import AuthManager
from rhx.errors import CLIError, ErrorCode
from rhx.models import (
    AuthStatus,
    CapabilitySet,
    OrderIntentCrypto,
    OrderResult,
)
from rhx.providers.base import OrderIntent


class RobinhoodCryptoProvider:
    name = "crypto"

    def __init__(self, auth: AuthManager, base_url: str = "https://trading.robinhood.com") -> None:
        self.auth = auth
        self.base_url = base_url.rstrip("/")

    def capabilities(self) -> CapabilitySet:
        return CapabilitySet(stocks=False, crypto=True, options=False, options_spreads=False)

    def _credentials(self) -> tuple[str, str]:
        api_key, private_key_b64 = self.auth.crypto_credentials()
        if not api_key or not private_key_b64:
            raise CLIError(
                code=ErrorCode.AUTH_REQUIRED,
                message="Missing RH_CRYPTO_API_KEY or RH_CRYPTO_PRIVATE_KEY_B64",
            )
        return api_key, private_key_b64

    def _sign(self, private_key_b64: str, message: str) -> str:
        try:
            key_bytes = base64.b64decode(private_key_b64)
        except Exception as exc:
            raise CLIError(code=ErrorCode.AUTH_REQUIRED, message=f"Invalid crypto private key encoding: {exc}") from exc

        # Ed25519 private key material should be a 32-byte seed or 64-byte secret/public concat.
        if len(key_bytes) not in (32, 64):
            raise CLIError(
                code=ErrorCode.AUTH_REQUIRED,
                message="Invalid crypto private key length; expected 32 or 64 decoded bytes",
            )

        seed = key_bytes[:32]
        signing_key = SigningKey(seed)
        signature = signing_key.sign(message.encode("utf-8")).signature
        return base64.b64encode(signature).decode("utf-8")

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        api_key, private_key_b64 = self._credentials()
        timestamp = str(int(time.time()))
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True) if payload is not None else ""

        signing_payload = f"{api_key}{timestamp}{path}{method.upper()}{body}"
        signature = self._sign(private_key_b64, signing_payload)

        headers = {
            "x-api-key": api_key,
            "x-signature": signature,
            "x-timestamp": timestamp,
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"

        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=20.0) as client:
            response = client.request(method, url, headers=headers, json=payload, params=params)

        if response.status_code == 429:
            raise CLIError(code=ErrorCode.RATE_LIMITED, message="Robinhood crypto API rate limit", retriable=True)
        if response.status_code in (401, 403):
            raise CLIError(code=ErrorCode.AUTH_REQUIRED, message=f"Crypto auth failed: {response.text}")
        if response.status_code >= 400:
            raise CLIError(code=ErrorCode.BROKER_REJECTED, message=f"Crypto API error {response.status_code}: {response.text}")

        if response.content:
            try:
                return response.json()
            except Exception:
                return {"text": response.text}
        return {}

    def auth_status(self) -> AuthStatus:
        try:
            self._request("GET", "/api/v1/crypto/trading/accounts/")
            return AuthStatus(provider="crypto", authenticated=True, detail="Authenticated")
        except CLIError as exc:
            return AuthStatus(
                provider="crypto",
                authenticated=False,
                mfa_required=False,
                detail=exc.message,
            )

    def account_summary(self) -> dict[str, Any]:
        data = self._request("GET", "/api/v1/crypto/trading/accounts/")
        return data if isinstance(data, dict) else {"accounts": data}

    def positions(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/api/v1/crypto/trading/holdings/")
        if isinstance(data, dict):
            for key in ("results", "holdings"):
                if isinstance(data.get(key), list):
                    return data[key]
            return [data]
        return data if isinstance(data, list) else []

    def quote(self, symbol: str) -> dict[str, Any]:
        data = self._request(
            "GET",
            "/api/v1/crypto/marketdata/best_bid_ask/",
            params={"symbol": symbol},
        )
        return {"symbol": symbol, "quote": data}

    def place_order(self, intent: OrderIntent) -> OrderResult:
        if not isinstance(intent, OrderIntentCrypto):
            raise CLIError(code=ErrorCode.VALIDATION_ERROR, message="Crypto provider only supports crypto orders")

        order_type = intent.order_type
        amount_in = intent.amount_in

        payload: dict[str, Any] = {
            "client_order_id": str(uuid.uuid4()),
            "side": intent.side,
            "symbol": intent.symbol,
            "type": order_type,
            "time_in_force": intent.time_in_force,
        }

        if order_type == "market":
            if amount_in == "quantity":
                payload["market_order_config"] = {"asset_quantity": str(intent.quantity)}
            else:
                payload["market_order_config"] = {"quote_amount": str(intent.notional_usd)}
        else:
            if amount_in == "quantity":
                payload["limit_order_config"] = {
                    "asset_quantity": str(intent.quantity),
                    "limit_price": str(intent.limit_price),
                }
            else:
                payload["limit_order_config"] = {
                    "quote_amount": str(intent.notional_usd),
                    "limit_price": str(intent.limit_price),
                }

        raw = self._request("POST", "/api/v1/crypto/trading/orders/", payload=payload)

        if isinstance(raw, dict):
            order_id = raw.get("id") or raw.get("order_id")
            state = raw.get("state") or raw.get("status")
        else:
            order_id = None
            state = None

        return OrderResult(
            provider=self.name,
            order_id=order_id,
            state=state,
            symbol=intent.symbol,
            side=intent.side,
            asset_type="crypto",
            raw=raw if isinstance(raw, dict) else {"response": raw},
        )

    def cancel_order(self, order_id: str, asset_type: str | None = None) -> dict[str, Any]:
        data = self._request("POST", f"/api/v1/crypto/trading/orders/{order_id}/cancel/")
        return {"asset_type": "crypto", "result": data}

    def get_order(self, order_id: str, asset_type: str | None = None) -> dict[str, Any]:
        data = self._request("GET", f"/api/v1/crypto/trading/orders/{order_id}/")
        return {"asset_type": "crypto", "order": data}

    def list_orders(self, open_only: bool = False, asset_type: str | None = None) -> list[dict[str, Any]]:
        params = {"state": "open"} if open_only else None
        data = self._request("GET", "/api/v1/crypto/trading/orders/", params=params)

        if isinstance(data, dict):
            if isinstance(data.get("results"), list):
                return data["results"]
            return [data]
        return data if isinstance(data, list) else []
