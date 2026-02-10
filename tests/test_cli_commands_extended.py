from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import rhx.cli as cli
from rhx.models import AuthStatus, CapabilitySet


class DummyStore:
    def __init__(self):
        self.deleted_crypto = False

    def delete_crypto_credentials(self, profile: str):
        del profile
        self.deleted_crypto = True


class DummyAuthManager:
    crypto_ok = True

    def __init__(self, profile: str, session_dir: Path):
        self.profile = profile
        self.session_dir = session_dir
        self.session_pickle_path = session_dir / f"robinhood_{profile}.pickle"
        self.store = DummyStore()
        self.logged_out = False

    def ensure_brokerage_authenticated(self, interactive: bool | None = None, force: bool = False):
        del interactive, force
        return AuthStatus(provider="brokerage", authenticated=True, detail="ok")

    def brokerage_status(self):
        return AuthStatus(provider="brokerage", authenticated=True, detail="ok")

    def refresh_brokerage(self, interactive: bool = True):
        del interactive
        return AuthStatus(provider="brokerage", authenticated=True, detail="refreshed")

    def logout_brokerage(self, forget_creds: bool = False):
        del forget_creds
        self.logged_out = True

    def crypto_status(self):
        return AuthStatus(provider="crypto", authenticated=self.__class__.crypto_ok, detail="ok")


class DummyResult:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self, mode="python"):
        del mode
        return self.payload


class DummyBrokerageProvider:
    name = "brokerage"

    def __init__(self, auth):
        self.auth = auth

    def capabilities(self):
        return CapabilitySet(stocks=True, crypto=True, options=True, options_spreads=True)

    def auth_status(self):
        return AuthStatus(provider="brokerage", authenticated=True, detail="ok")

    def account_summary(self):
        return {"cash": "100"}

    def positions(self):
        return [{"asset_type": "stock", "symbol": "AAPL"}]

    def quote(self, symbol: str):
        return {"symbol": symbol}

    def place_order(self, intent):
        return DummyResult({"id": "ord-1", "asset_type": intent.asset_type, "symbol": intent.symbol})

    def cancel_order(self, order_id: str, asset_type: str | None = None):
        return {"id": order_id, "asset_type": asset_type or "stock"}

    def get_order(self, order_id: str, asset_type: str | None = None):
        return {"id": order_id, "asset_type": asset_type or "stock"}

    def list_orders(self, open_only: bool = False, asset_type: str | None = None):
        return [{"id": "1", "open_only": open_only, "asset_type": asset_type or "stock"}]

    def option_chains(self, symbol: str):
        return {"symbol": symbol}

    def option_contracts_find(self, symbol: str, expiration_date=None, strike_price=None, option_type=None):
        return [{"symbol": symbol, "expiration_date": expiration_date, "strike": strike_price, "option_type": option_type}]


class DummyCryptoProvider(DummyBrokerageProvider):
    name = "crypto"


class HumanQuoteBrokerageProvider(DummyBrokerageProvider):
    def quote(self, symbol: str):
        return {
            "asset_type": "stock",
            "symbol": symbol,
            "quote": {
                "bid_price": "274.50",
                "ask_price": "274.59",
                "last_trade_price": "273.79",
                "updated_at": "2026-02-10T23:32:36Z",
            },
        }


def _payload(result):
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_cli_happy_path_command_coverage(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(cli, "AuthManager", DummyAuthManager)
    monkeypatch.setattr(cli, "RobinStocksProvider", DummyBrokerageProvider)
    monkeypatch.setattr(cli, "RobinhoodCryptoProvider", DummyCryptoProvider)

    DummyAuthManager.crypto_ok = True

    runner = CliRunner()
    config_path = tmp_path / "config.toml"
    base = ["--json", "--config", str(config_path)]

    _payload(runner.invoke(cli.app, base + ["auth", "login", "--non-interactive", "--force"]))
    _payload(runner.invoke(cli.app, base + ["auth", "status"]))
    _payload(runner.invoke(cli.app, base + ["auth", "refresh", "--non-interactive"]))
    _payload(runner.invoke(cli.app, base + ["auth", "logout", "--forget-creds"]))

    live_on_payload = _payload(runner.invoke(cli.app, base + ["live", "on", "--yes"]))
    live_token = live_on_payload["data"]["live_confirm_token"]
    assert live_token
    _payload(runner.invoke(cli.app, base + ["live", "status"]))
    _payload(runner.invoke(cli.app, base + ["account", "summary"]))
    _payload(runner.invoke(cli.app, base + ["positions", "list"]))

    stock_quote = _payload(runner.invoke(cli.app, base + ["quote", "get", "AAPL"]))
    assert stock_quote["provider"] == "brokerage"

    crypto_quote = _payload(runner.invoke(cli.app, base + ["quote", "get", "BTC-USD"]))
    assert crypto_quote["provider"] == "crypto"

    _payload(
        runner.invoke(
            cli.app,
            base
            + [
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
    )

    _payload(
        runner.invoke(
            cli.app,
            base
            + [
                "orders",
                "crypto",
                "place",
                "--symbol",
                "BTC-USD",
                "--side",
                "buy",
                "--type",
                "market",
                "--amount-in",
                "quantity",
                "--qty",
                "0.1",
                "--live-confirm-token",
                live_token,
            ],
        )
    )

    get_crypto = _payload(runner.invoke(cli.app, base + ["orders", "get", "abc", "--asset-type", "crypto"]))
    assert get_crypto["provider"] == "crypto"

    _payload(runner.invoke(cli.app, base + ["orders", "cancel", "abc", "--asset-type", "crypto"]))
    _payload(runner.invoke(cli.app, base + ["orders", "list", "--asset-type", "crypto", "--open"]))

    _payload(runner.invoke(cli.app, base + ["options", "chains", "AAPL"]))
    _payload(runner.invoke(cli.app, base + ["options", "contracts", "find", "--symbol", "AAPL", "--expiration-date", "2026-12-18"]))

    _payload(
        runner.invoke(
            cli.app,
            base
            + [
                "options",
                "orders",
                "place",
                "single",
                "--side",
                "buy",
                "--type",
                "limit",
                "--position-effect",
                "open",
                "--credit-or-debit",
                "debit",
                "--symbol",
                "AAPL",
                "--qty",
                "1",
                "--expiration-date",
                "2026-12-18",
                "--strike",
                "200",
                "--price",
                "1.2",
                "--live-confirm-token",
                live_token,
            ],
        )
    )

    _payload(
        runner.invoke(
            cli.app,
            base
            + [
                "options",
                "orders",
                "place",
                "credit-spread",
                "--symbol",
                "AAPL",
                "--qty",
                "1",
                "--price",
                "1.0",
                "--expiration-date",
                "2026-12-18",
                "--option-type",
                "call",
                "--short-strike",
                "200",
                "--long-strike",
                "205",
                "--live-confirm-token",
                live_token,
            ],
        )
    )

    _payload(
        runner.invoke(
            cli.app,
            base
            + [
                "options",
                "orders",
                "place",
                "debit-spread",
                "--symbol",
                "AAPL",
                "--qty",
                "1",
                "--price",
                "1.0",
                "--expiration-date",
                "2026-12-18",
                "--option-type",
                "call",
                "--short-strike",
                "200",
                "--long-strike",
                "205",
                "--live-confirm-token",
                live_token,
            ],
        )
    )

    _payload(runner.invoke(cli.app, base + ["options", "orders", "get", "oid"]))
    _payload(runner.invoke(cli.app, base + ["options", "orders", "cancel", "oid"]))
    _payload(runner.invoke(cli.app, base + ["options", "orders", "list", "--open"]))
    _payload(runner.invoke(cli.app, base + ["doctor"]))


def test_cli_live_on_prompt_decline(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(cli, "AuthManager", DummyAuthManager)
    monkeypatch.setattr(cli, "RobinStocksProvider", DummyBrokerageProvider)
    monkeypatch.setattr(cli, "RobinhoodCryptoProvider", DummyCryptoProvider)
    monkeypatch.setattr(cli.typer, "confirm", lambda msg: False)

    runner = CliRunner()
    config_path = tmp_path / "config.toml"
    result = runner.invoke(cli.app, ["--json", "--config", str(config_path), "live", "on"])

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "VALIDATION_ERROR"


def test_cli_validation_error_and_auto_fallback_to_brokerage(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(cli, "AuthManager", DummyAuthManager)
    monkeypatch.setattr(cli, "RobinStocksProvider", DummyBrokerageProvider)
    monkeypatch.setattr(cli, "RobinhoodCryptoProvider", DummyCryptoProvider)

    runner = CliRunner()
    config_path = tmp_path / "config.toml"
    base = ["--json", "--config", str(config_path)]

    live_on_payload = _payload(runner.invoke(cli.app, base + ["live", "on", "--yes"]))
    live_token = live_on_payload["data"]["live_confirm_token"]

    bad = runner.invoke(
        cli.app,
        base
        + [
            "orders",
            "crypto",
            "place",
            "--symbol",
            "BTC-USD",
            "--side",
            "buy",
                "--type",
                "market",
                "--amount-in",
                "quantity",
                "--live-confirm-token",
                live_token,
            ],
        )
    assert bad.exit_code == 2
    bad_payload = json.loads(bad.output)
    assert bad_payload["error"]["code"] == "VALIDATION_ERROR"

    DummyAuthManager.crypto_ok = False
    fallback = runner.invoke(cli.app, base + ["orders", "get", "abc", "--asset-type", "crypto"])
    assert fallback.exit_code == 0
    fallback_payload = json.loads(fallback.output)
    assert fallback_payload["provider"] == "brokerage"


def test_cli_summary_default_full_and_selectors(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(cli, "AuthManager", DummyAuthManager)
    monkeypatch.setattr(cli, "RobinStocksProvider", DummyBrokerageProvider)
    monkeypatch.setattr(cli, "RobinhoodCryptoProvider", DummyCryptoProvider)

    runner = CliRunner()
    config_path = tmp_path / "config.toml"
    base = ["--json", "--config", str(config_path)]

    summary_positions = _payload(runner.invoke(cli.app, base + ["positions", "list"]))
    assert summary_positions["meta"]["output_schema"] == "v2"
    assert summary_positions["meta"]["view"] == "summary"
    assert summary_positions["data"] == [
        {
            "asset_type": "stock",
            "symbol": "AAPL",
            "position_id": None,
            "quantity": None,
            "quantity_available": None,
            "quantity_held": None,
            "cost_basis": None,
            "market_value": None,
            "average_buy_price": None,
            "updated_at": None,
        }
    ]

    full_positions = _payload(runner.invoke(cli.app, base + ["--view", "full", "positions", "list"]))
    assert full_positions["meta"]["view"] == "full"
    assert full_positions["data"] == [{"asset_type": "stock", "symbol": "AAPL"}]

    selected_positions = _payload(runner.invoke(cli.app, base + ["--fields", "symbol,quantity", "positions", "list"]))
    assert selected_positions["data"] == [{"symbol": "AAPL", "quantity": None}]
    assert selected_positions["meta"]["fields"] == ["symbol", "quantity"]

    limited_orders = _payload(runner.invoke(cli.app, base + ["--limit", "1", "orders", "list"]))
    assert limited_orders["meta"]["total_count"] == 1
    assert limited_orders["meta"]["returned_count"] == 1
    assert limited_orders["meta"]["truncated"] is False


def test_cli_output_selector_validation_and_json_only_enforcement(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(cli, "AuthManager", DummyAuthManager)
    monkeypatch.setattr(cli, "RobinStocksProvider", DummyBrokerageProvider)
    monkeypatch.setattr(cli, "RobinhoodCryptoProvider", DummyCryptoProvider)

    runner = CliRunner()
    config_path = tmp_path / "config.toml"
    base = ["--json", "--config", str(config_path)]

    unknown_fields = runner.invoke(cli.app, base + ["--fields", "bad_field", "positions", "list"])
    assert unknown_fields.exit_code == 2
    unknown_payload = json.loads(unknown_fields.output)
    assert unknown_payload["error"]["code"] == "VALIDATION_ERROR"
    assert unknown_payload["meta"]["output_schema"] == "v2"
    assert unknown_payload["meta"]["view"] == "summary"

    fields_on_full = runner.invoke(cli.app, base + ["--view", "full", "--fields", "symbol", "positions", "list"])
    assert fields_on_full.exit_code == 2
    fields_on_full_payload = json.loads(fields_on_full.output)
    assert fields_on_full_payload["error"]["code"] == "VALIDATION_ERROR"
    assert fields_on_full_payload["meta"]["output_schema"] == "v2"
    assert fields_on_full_payload["meta"]["view"] == "full"

    no_json_view = runner.invoke(cli.app, ["--config", str(config_path), "--view", "full", "positions", "list"])
    assert no_json_view.exit_code == 2
    assert "VALIDATION_ERROR" in no_json_view.output


def test_cli_human_mode_outputs_compact_summary(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(cli, "AuthManager", DummyAuthManager)
    monkeypatch.setattr(cli, "RobinStocksProvider", HumanQuoteBrokerageProvider)
    monkeypatch.setattr(cli, "RobinhoodCryptoProvider", DummyCryptoProvider)

    runner = CliRunner()
    config_path = tmp_path / "config.toml"
    result = runner.invoke(cli.app, ["--human", "--config", str(config_path), "quote", "get", "AAPL"])
    assert result.exit_code == 0, result.output
    assert "OK quote get" in result.output
    assert "bid_price" in result.output
    assert "ask_price" in result.output


def test_cli_human_and_json_are_mutually_exclusive(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(cli, "AuthManager", DummyAuthManager)
    monkeypatch.setattr(cli, "RobinStocksProvider", DummyBrokerageProvider)
    monkeypatch.setattr(cli, "RobinhoodCryptoProvider", DummyCryptoProvider)

    runner = CliRunner()
    config_path = tmp_path / "config.toml"
    result = runner.invoke(cli.app, ["--json", "--human", "--config", str(config_path), "live", "status"])
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert "--human cannot be used with --json" in payload["error"]["message"]
    assert payload["meta"]["output_schema"] == "v2"
