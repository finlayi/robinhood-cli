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
        return {"cash": "100.00"}

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


def test_json_envelope_shape(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "RobinStocksProvider", DummyBrokerageProvider)
    monkeypatch.setattr(cli, "RobinhoodCryptoProvider", DummyCryptoProvider)

    runner = CliRunner()
    config_path = tmp_path / "config.toml"

    result = runner.invoke(cli.app, ["--json", "--config", str(config_path), "live", "status"])
    assert result.exit_code == 0, result.output

    payload = json.loads(result.output)
    assert set(payload.keys()) == {"ok", "command", "provider", "data", "error", "meta"}
    assert payload["ok"] is True
    assert payload["command"] == "live status"
    assert isinstance(payload["meta"], dict)
