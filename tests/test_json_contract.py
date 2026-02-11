from __future__ import annotations

import json
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from typer.testing import CliRunner

import rhx.cli as cli
from rhx.models import AuthStatus


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

    def list_orders(
        self,
        open_only: bool = False,
        asset_type: str | None = None,
        symbol_resolve_limit: int | None = None,
    ):
        del open_only, asset_type, symbol_resolve_limit
        return []

    def option_chains(self, symbol: str):
        return {"symbol": symbol}

    def option_contracts_find(self, symbol: str, expiration_date=None, strike_price=None, option_type=None):
        del expiration_date, strike_price, option_type
        return [{"symbol": symbol}]


class DummyCryptoProvider(DummyBrokerageProvider):
    name = "crypto"


class NoisyAuthManager:
    def __init__(self, profile: str, session_dir: Path, suppress_external_output: bool = False):
        self.profile = profile
        self.session_dir = session_dir
        self.session_pickle_path = session_dir / f"robinhood_{profile}.pickle"
        self.store = type("Store", (), {"delete_crypto_credentials": lambda self, profile: None})()
        self.suppress_external_output = suppress_external_output

    @contextmanager
    def external_output_guard(self):
        if not self.suppress_external_output:
            yield
            return
        sink = StringIO()
        with redirect_stdout(sink), redirect_stderr(sink):
            yield

    def ensure_brokerage_authenticated(self, interactive: bool | None = None, force: bool = False):
        del interactive, force
        with self.external_output_guard():
            print("Starting login process...")
            print("Loading Market Data |", end="\r")
        return AuthStatus(provider="brokerage", authenticated=True, detail="ok")

    def brokerage_status(self):
        return self.ensure_brokerage_authenticated(interactive=False, force=False)

    def refresh_brokerage(self, interactive: bool = True):
        del interactive
        return self.brokerage_status()

    def logout_brokerage(self, forget_creds: bool = False):
        del forget_creds

    def crypto_status(self):
        return AuthStatus(provider="crypto", authenticated=False, detail="not configured")


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
    assert payload["meta"]["output_schema"] == "v2"
    assert payload["meta"]["view"] == "summary"


def test_json_output_stays_parseable_when_brokerage_is_noisy(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "AuthManager", NoisyAuthManager)
    monkeypatch.setattr(cli, "RobinStocksProvider", DummyBrokerageProvider)
    monkeypatch.setattr(cli, "RobinhoodCryptoProvider", DummyCryptoProvider)

    runner = CliRunner()
    config_path = tmp_path / "config.toml"

    result = runner.invoke(cli.app, ["--json", "--config", str(config_path), "auth", "status"])
    assert result.exit_code == 0, result.output
    assert "Starting login process" not in result.output
    assert "Loading Market Data" not in result.output

    payload = json.loads(result.output)
    assert set(payload.keys()) == {"ok", "command", "provider", "data", "error", "meta"}
    assert payload["command"] == "auth status"
