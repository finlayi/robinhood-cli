from __future__ import annotations

import json

from typer.testing import CliRunner

import rhx.cli as cli


class DummyBrokerageProvider:
    name = "brokerage"

    def __init__(self, auth):
        del auth

    def capabilities(self):
        return type("Caps", (), {"model_dump": lambda self, mode=None: {"stocks": True, "crypto": True, "options": True, "options_spreads": True}})()

    def auth_status(self):
        return type("Status", (), {"model_dump": lambda self, mode=None: {"authenticated": True}})()

    def account_summary(self):
        return {"ok": True}

    def positions(self):
        return []

    def quote(self, symbol: str):
        return {"symbol": symbol}

    def place_order(self, intent):
        return type("Result", (), {"model_dump": lambda self, mode=None: {"id": "1", "intent": str(intent)}})()

    def cancel_order(self, order_id: str, asset_type: str | None = None):
        del asset_type
        return {"id": order_id}

    def get_order(self, order_id: str, asset_type: str | None = None):
        del asset_type
        return {"id": order_id}

    def list_orders(self, open_only: bool = False, asset_type: str | None = None):
        del open_only, asset_type
        return []

    def option_chains(self, symbol: str):
        return {"symbol": symbol}

    def option_contracts_find(self, symbol: str, expiration_date=None, strike_price=None, option_type=None):
        del expiration_date, strike_price, option_type
        return [{"symbol": symbol}]


class DummyCryptoProvider(DummyBrokerageProvider):
    name = "crypto"


def test_live_toggle_and_guardrail(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "RobinStocksProvider", DummyBrokerageProvider)
    monkeypatch.setattr(cli, "RobinhoodCryptoProvider", DummyCryptoProvider)

    runner = CliRunner()
    config_path = tmp_path / "config.toml"

    status = runner.invoke(cli.app, ["--json", "--config", str(config_path), "live", "status"])
    assert status.exit_code == 0, status.output
    payload = json.loads(status.output)
    assert payload["ok"] is True
    assert payload["data"]["live_mode"] is False

    blocked = runner.invoke(
        cli.app,
        [
            "--json",
            "--config",
            str(config_path),
            "orders",
            "stock",
            "place",
            "--symbol",
            "AAPL",
            "--side",
            "buy",
            "--type",
            "market",
            "--qty",
            "1",
        ],
    )
    assert blocked.exit_code == 6
    blocked_payload = json.loads(blocked.output)
    assert blocked_payload["error"]["code"] == "LIVE_MODE_OFF"

    enabled = runner.invoke(cli.app, ["--json", "--config", str(config_path), "live", "on", "--yes"])
    assert enabled.exit_code == 0, enabled.output
    enabled_payload = json.loads(enabled.output)
    live_token = enabled_payload["data"]["live_confirm_token"]
    assert live_token

    status_after = runner.invoke(cli.app, ["--json", "--config", str(config_path), "live", "status"])
    payload_after = json.loads(status_after.output)
    assert payload_after["data"]["live_mode"] is True
    assert payload_after["data"]["live_unlock"]["active"] is True

    blocked_without_token = runner.invoke(
        cli.app,
        [
            "--json",
            "--config",
            str(config_path),
            "orders",
            "stock",
            "place",
            "--symbol",
            "AAPL",
            "--side",
            "buy",
            "--type",
            "market",
            "--qty",
            "1",
        ],
    )
    assert blocked_without_token.exit_code == 6
    blocked_without_token_payload = json.loads(blocked_without_token.output)
    assert blocked_without_token_payload["error"]["code"] == "SAFETY_POLICY_BLOCK"

    allowed_with_token = runner.invoke(
        cli.app,
        [
            "--json",
            "--config",
            str(config_path),
            "orders",
            "stock",
            "place",
            "--symbol",
            "AAPL",
            "--side",
            "buy",
            "--type",
            "market",
            "--qty",
            "1",
            "--live-confirm-token",
            live_token,
        ],
    )
    assert allowed_with_token.exit_code == 0, allowed_with_token.output
