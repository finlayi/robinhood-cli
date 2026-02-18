from __future__ import annotations

import json
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import pytest
from typer.testing import CliRunner

import rhx.cli as cli
from rhx.models import AuthStatus, BrokeragePassiveStatus, CapabilitySet


class DummyStore:
    def __init__(self):
        self.deleted_crypto = False

    def delete_crypto_credentials(self, profile: str):
        del profile
        self.deleted_crypto = True


class DummyAuthManager:
    crypto_ok = True

    def __init__(
        self,
        profile: str,
        session_dir: Path,
        suppress_external_output: bool = False,
        verbose: bool = False,
    ):
        self.profile = profile
        self.session_dir = session_dir
        self.session_pickle_path = session_dir / f"robinhood_{profile}.pickle"
        self.store = DummyStore()
        self.logged_out = False
        self.suppress_external_output = suppress_external_output
        self.verbose = verbose

    @contextmanager
    def external_output_guard(self):
        yield

    def ensure_brokerage_authenticated(self, interactive: bool | None = None, force: bool = False):
        del interactive, force
        return AuthStatus(provider="brokerage", authenticated=True, detail="ok")

    def brokerage_status(self):
        return AuthStatus(provider="brokerage", authenticated=True, detail="ok")

    def brokerage_passive_status(self):
        return BrokeragePassiveStatus(
            session_pickle_exists=True,
            credentials_present=True,
            session_ready=True,
            detail="Session pickle and credentials are available",
        )

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

    def quotes(self, symbols: list[str]):
        return [self.quote(symbol) for symbol in symbols]

    def place_order(self, intent):
        return DummyResult({"id": "ord-1", "asset_type": intent.asset_type, "symbol": intent.symbol})

    def cancel_order(self, order_id: str, asset_type: str | None = None):
        return {"id": order_id, "asset_type": asset_type or "stock"}

    def get_order(self, order_id: str, asset_type: str | None = None):
        return {"id": order_id, "asset_type": asset_type or "stock"}

    def list_orders(
        self,
        open_only: bool = False,
        asset_type: str | None = None,
        symbol_resolve_limit: int | None = None,
    ):
        del symbol_resolve_limit
        return [{"id": "1", "open_only": open_only, "asset_type": asset_type or "stock"}]

    def option_chains(self, symbol: str):
        return {"symbol": symbol}

    def option_contracts_find(self, symbol: str, expiration_date=None, strike_price=None, option_type=None):
        return [{"symbol": symbol, "expiration_date": expiration_date, "strike": strike_price, "option_type": option_type}]

    def option_expirations(self, symbol: str):
        return ["2026-12-18"]

    def option_strikes(self, symbol: str, expiration_date: str, option_type: str | None = None):
        del symbol, expiration_date, option_type
        return [100.0, 105.0]

    def option_quote_get(self, symbol: str, expiration_date: str, strike_price: float, option_type: str):
        return {
            "contract_id": "oid",
            "symbol": symbol,
            "expiration_date": expiration_date,
            "strike_price": strike_price,
            "option_type": option_type,
            "bid_price": "1.0",
            "ask_price": "1.2",
            "mark_price": "1.1",
            "last_trade_price": "1.1",
            "implied_volatility": "0.3",
            "delta": "0.5",
            "gamma": "0.1",
            "theta": "-0.05",
            "vega": "0.02",
            "rho": "0.01",
            "open_interest": "100",
            "volume": "25",
            "updated_at": "2026-02-11T00:00:00Z",
            "tradability": "tradable",
            "state": "active",
        }

    def option_quotes_list(self, symbol: str, expiration_date: str, option_type: str | None = None):
        return [self.option_quote_get(symbol, expiration_date, 100.0, option_type or "call")]


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


class NoisyAuthManager(DummyAuthManager):
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


class NoisyBrokerageProvider(DummyBrokerageProvider):
    def option_contracts_find(self, symbol: str, expiration_date=None, strike_price=None, option_type=None):
        with self.auth.external_output_guard():
            print("Found Additional pages.")
            print("Loading Market Data /", end="\r")
        return super().option_contracts_find(
            symbol=symbol,
            expiration_date=expiration_date,
            strike_price=strike_price,
            option_type=option_type,
        )


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
    assert summary_positions["meta"]["output_schema"] == "v3"
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
    assert unknown_payload["meta"]["output_schema"] == "v3"
    assert unknown_payload["meta"]["view"] == "summary"

    fields_on_full = runner.invoke(cli.app, base + ["--view", "full", "--fields", "symbol", "positions", "list"])
    assert fields_on_full.exit_code == 2
    fields_on_full_payload = json.loads(fields_on_full.output)
    assert fields_on_full_payload["error"]["code"] == "VALIDATION_ERROR"
    assert fields_on_full_payload["meta"]["output_schema"] == "v3"
    assert fields_on_full_payload["meta"]["view"] == "full"

    no_json_view = runner.invoke(cli.app, ["--config", str(config_path), "--view", "full", "positions", "list"])
    assert no_json_view.exit_code == 2
    assert "VALIDATION_ERROR" in no_json_view.output


def test_cli_json_mode_suppresses_noisy_brokerage_output(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(cli, "AuthManager", NoisyAuthManager)
    monkeypatch.setattr(cli, "RobinStocksProvider", NoisyBrokerageProvider)
    monkeypatch.setattr(cli, "RobinhoodCryptoProvider", DummyCryptoProvider)

    runner = CliRunner()
    config_path = tmp_path / "config.toml"
    base = ["--json", "--config", str(config_path)]

    auth_status = runner.invoke(cli.app, base + ["auth", "status"])
    assert auth_status.exit_code == 0, auth_status.output
    assert "Starting login process" not in auth_status.output
    assert "Loading Market Data" not in auth_status.output
    auth_payload = json.loads(auth_status.output)
    assert set(auth_payload.keys()) == {"ok", "command", "provider", "data", "error", "meta"}
    assert auth_payload["command"] == "auth status"

    contracts = runner.invoke(
        cli.app,
        base + ["options", "contracts", "find", "--symbol", "AAPL", "--expiration-date", "2026-12-18"],
    )
    assert contracts.exit_code == 0, contracts.output
    assert "Found Additional pages." not in contracts.output
    assert "Loading Market Data" not in contracts.output
    contracts_payload = json.loads(contracts.output)
    assert set(contracts_payload.keys()) == {"ok", "command", "provider", "data", "error", "meta"}
    assert contracts_payload["command"] == "options contracts find"


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
    assert payload["meta"]["output_schema"] == "v3"


def test_cli_rejects_fractional_stock_qty_with_notional_guidance(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(cli, "AuthManager", DummyAuthManager)
    monkeypatch.setattr(cli, "RobinStocksProvider", DummyBrokerageProvider)
    monkeypatch.setattr(cli, "RobinhoodCryptoProvider", DummyCryptoProvider)

    runner = CliRunner()
    config_path = tmp_path / "config.toml"
    base = ["--json", "--config", str(config_path)]

    live_on_payload = _payload(runner.invoke(cli.app, base + ["live", "on", "--yes"]))
    live_token = live_on_payload["data"]["live_confirm_token"]

    result = runner.invoke(
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
            "0.25",
            "--live-confirm-token",
            live_token,
        ],
    )

    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert "Use --notional-usd for fractional stock orders" in payload["error"]["message"]


def test_cli_auth_status_is_passive_and_verify_is_active(monkeypatch: pytest.MonkeyPatch, tmp_path):
    class TrackingAuth(DummyAuthManager):
        passive_calls = 0
        active_calls = 0

        def brokerage_passive_status(self):
            self.__class__.passive_calls += 1
            return super().brokerage_passive_status()

        def brokerage_status(self):
            self.__class__.active_calls += 1
            return super().brokerage_status()

    monkeypatch.setattr(cli, "AuthManager", TrackingAuth)
    monkeypatch.setattr(cli, "RobinStocksProvider", DummyBrokerageProvider)
    monkeypatch.setattr(cli, "RobinhoodCryptoProvider", DummyCryptoProvider)

    runner = CliRunner()
    config_path = tmp_path / "config.toml"
    base = ["--json", "--config", str(config_path)]

    status_payload = _payload(runner.invoke(cli.app, base + ["auth", "status"]))
    verify_payload = _payload(runner.invoke(cli.app, base + ["auth", "verify"]))

    assert status_payload["command"] == "auth status"
    assert verify_payload["command"] == "auth verify"
    assert TrackingAuth.passive_calls == 1
    assert TrackingAuth.active_calls == 1


def test_cli_quote_list_strict_and_non_strict_modes(monkeypatch: pytest.MonkeyPatch, tmp_path):
    class PartialQuoteProvider(DummyBrokerageProvider):
        def quotes(self, symbols: list[str]):
            first = symbols[0]
            return [
                {
                    "asset_type": "stock",
                    "symbol": first,
                    "quote": {"bid_price": "10.0", "ask_price": "10.1", "last_trade_price": "10.05"},
                }
            ]

    monkeypatch.setattr(cli, "AuthManager", DummyAuthManager)
    monkeypatch.setattr(cli, "RobinStocksProvider", PartialQuoteProvider)
    monkeypatch.setattr(cli, "RobinhoodCryptoProvider", DummyCryptoProvider)

    runner = CliRunner()
    config_path = tmp_path / "config.toml"
    base = ["--json", "--config", str(config_path)]

    non_strict = _payload(runner.invoke(cli.app, base + ["quote", "list", "--symbols", "AAPL,MSFT"]))
    assert len(non_strict["data"]) == 2
    assert non_strict["data"][0]["symbol"] == "AAPL"
    assert non_strict["data"][0]["error"] is None
    assert non_strict["data"][1]["symbol"] == "MSFT"
    assert "No quote returned" in non_strict["data"][1]["error"]

    strict = runner.invoke(cli.app, base + ["quote", "list", "--symbols", "AAPL,MSFT", "--strict"])
    assert strict.exit_code != 0
    strict_payload = json.loads(strict.output)
    assert strict_payload["error"]["code"] == "BROKER_REJECTED"


def test_cli_options_discovery_and_quotes_filters(monkeypatch: pytest.MonkeyPatch, tmp_path):
    class OptionDataProvider(DummyBrokerageProvider):
        def option_expirations(self, symbol: str):
            assert symbol == "AAPL"
            return ["2026-12-18", "2027-01-15"]

        def option_strikes(self, symbol: str, expiration_date: str, option_type: str | None = None):
            assert symbol == "AAPL"
            assert expiration_date == "2026-12-18"
            assert option_type == "call"
            return [90.0, 100.0, 110.0]

        def option_quote_get(self, symbol: str, expiration_date: str, strike_price: float, option_type: str):
            return {
                "contract_id": "contract-1",
                "symbol": symbol,
                "expiration_date": expiration_date,
                "strike_price": strike_price,
                "option_type": option_type,
                "bid_price": "1.00",
                "ask_price": "1.10",
                "mark_price": "1.05",
                "last_trade_price": "1.02",
                "implied_volatility": "0.30",
                "delta": "0.55",
                "gamma": "0.11",
                "theta": "-0.03",
                "vega": "0.04",
                "rho": "0.01",
                "open_interest": "120",
                "volume": "30",
                "updated_at": "2026-02-11T00:00:00Z",
                "tradability": "tradable",
                "state": "active",
            }

        def option_quotes_list(self, symbol: str, expiration_date: str, option_type: str | None = None):
            return [
                self.option_quote_get(symbol, expiration_date, 100.0, option_type or "call"),
                {
                    "contract_id": "contract-2",
                    "symbol": symbol,
                    "expiration_date": expiration_date,
                    "strike_price": 110.0,
                    "option_type": option_type or "call",
                    "bid_price": "0.50",
                    "ask_price": "0.60",
                    "mark_price": "0.55",
                    "last_trade_price": "0.52",
                    "implied_volatility": "0.20",
                    "delta": "0.25",
                    "gamma": "0.08",
                    "theta": "-0.02",
                    "vega": "0.02",
                    "rho": "0.00",
                    "open_interest": "5",
                    "volume": "2",
                    "updated_at": "2026-02-11T00:00:00Z",
                    "tradability": "tradable",
                    "state": "active",
                },
            ]

    monkeypatch.setattr(cli, "AuthManager", DummyAuthManager)
    monkeypatch.setattr(cli, "RobinStocksProvider", OptionDataProvider)
    monkeypatch.setattr(cli, "RobinhoodCryptoProvider", DummyCryptoProvider)

    runner = CliRunner()
    config_path = tmp_path / "config.toml"
    base = ["--json", "--config", str(config_path)]

    expirations = _payload(runner.invoke(cli.app, base + ["options", "expirations", "AAPL"]))
    assert expirations["data"]["expiration_count"] == 2

    strikes = _payload(
        runner.invoke(
            cli.app,
            base + ["options", "strikes", "AAPL", "--expiration-date", "2026-12-18", "--option-type", "call"],
        )
    )
    assert strikes["data"]["strike_count"] == 3

    quote_get = _payload(
        runner.invoke(
            cli.app,
            base
            + [
                "options",
                "quotes",
                "get",
                "--symbol",
                "AAPL",
                "--expiration-date",
                "2026-12-18",
                "--strike",
                "100",
                "--option-type",
                "call",
            ],
        )
    )
    assert quote_get["data"]["contract_id"] == "contract-1"

    quote_list = _payload(
        runner.invoke(
            cli.app,
            base
            + [
                "options",
                "quotes",
                "list",
                "--symbol",
                "AAPL",
                "--expiration-date",
                "2026-12-18",
                "--option-type",
                "call",
                "--min-oi",
                "10",
                "--delta-min",
                "0.4",
                "--sort",
                "delta",
                "--descending",
                "--query-limit",
                "1",
                "--offset",
                "0",
            ],
        )
    )
    assert len(quote_list["data"]) == 1
    assert quote_list["meta"]["query_total_count"] == 1
    assert quote_list["meta"]["query_returned_count"] == 1
    assert quote_list["data"][0]["contract_id"] == "contract-1"


def test_cli_options_orders_list_filters_and_query_pagination(monkeypatch: pytest.MonkeyPatch, tmp_path):
    class OptionOrdersProvider(DummyBrokerageProvider):
        def list_orders(self, open_only: bool = False, asset_type: str | None = None, symbol_resolve_limit: int | None = None):
            del open_only, asset_type, symbol_resolve_limit
            return [
                {
                    "id": "1",
                    "chain_symbol": "AAPL",
                    "state": "filled",
                    "strategy": "long_call",
                    "created_at": "2026-02-01T12:00:00Z",
                    "updated_at": "2026-02-02T12:00:00Z",
                },
                {
                    "id": "2",
                    "chain_symbol": "AAPL",
                    "state": "filled",
                    "strategy": "long_call",
                    "created_at": "2026-02-03T12:00:00Z",
                    "updated_at": "2026-02-04T12:00:00Z",
                },
            ]

    monkeypatch.setattr(cli, "AuthManager", DummyAuthManager)
    monkeypatch.setattr(cli, "RobinStocksProvider", OptionOrdersProvider)
    monkeypatch.setattr(cli, "RobinhoodCryptoProvider", DummyCryptoProvider)

    runner = CliRunner()
    config_path = tmp_path / "config.toml"
    base = ["--json", "--config", str(config_path)]

    payload = _payload(
        runner.invoke(
            cli.app,
            base
            + [
                "options",
                "orders",
                "list",
                "--symbol",
                "AAPL",
                "--state",
                "filled",
                "--strategy",
                "long_call",
                "--from-date",
                "2026-02-01",
                "--to-date",
                "2026-02-28",
                "--sort",
                "updated_at",
                "--descending",
                "--query-limit",
                "1",
                "--offset",
                "1",
            ],
        )
    )
    assert len(payload["data"]) == 1
    assert payload["meta"]["query_total_count"] == 2
    assert payload["meta"]["query_returned_count"] == 1
    assert payload["meta"]["query_offset"] == 1


def test_cli_portfolio_analyze_outputs_risk_sections(monkeypatch: pytest.MonkeyPatch, tmp_path):
    class PortfolioProvider(DummyBrokerageProvider):
        def account_summary(self):
            return {
                "account_profile": {
                    "cash": "-20",
                    "buying_power": "500",
                    "margin_balances": {"settled_amount_borrowed": "100"},
                    "cash_available_for_withdrawal": "200",
                },
                "portfolio_profile": {"equity": "1200", "market_value": "1200", "withdrawable_amount": "200"},
            }

        def positions(self):
            return [
                {"asset_type": "stock", "symbol": "AAPL", "quantity": "10", "clearing_cost_basis": "700"},
                {"asset_type": "stock", "symbol": "MSFT", "quantity": "1", "clearing_cost_basis": "200"},
            ]

        def quotes(self, symbols: list[str]):
            rows = []
            for symbol in symbols:
                if symbol == "AAPL":
                    rows.append({"asset_type": "stock", "symbol": "AAPL", "quote": {"last_trade_price": "100"}})
                elif symbol == "MSFT":
                    rows.append({"asset_type": "stock", "symbol": "MSFT", "quote": {"last_trade_price": "200"}})
            return rows

    monkeypatch.setattr(cli, "AuthManager", DummyAuthManager)
    monkeypatch.setattr(cli, "RobinStocksProvider", PortfolioProvider)
    monkeypatch.setattr(cli, "RobinhoodCryptoProvider", DummyCryptoProvider)

    runner = CliRunner()
    config_path = tmp_path / "config.toml"
    base = ["--json", "--config", str(config_path)]

    payload = _payload(runner.invoke(cli.app, base + ["portfolio", "analyze", "--top", "2"]))
    assert "account" in payload["data"]
    assert "concentration" in payload["data"]
    assert "exposure" in payload["data"]
    assert "alerts" in payload["data"]
    assert len(payload["data"]["allocation"]) == 2
    alert_codes = {alert["code"] for alert in payload["data"]["alerts"]}
    assert "LARGEST_POSITION_CONCENTRATION" in alert_codes
    assert "NEGATIVE_CASH" in alert_codes
