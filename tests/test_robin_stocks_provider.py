from __future__ import annotations

from contextlib import contextmanager

import pytest

from rhx.errors import CLIError, ErrorCode
from rhx.models import OrderIntentCrypto, OrderIntentOptionSingle, OrderIntentOptionSpread, OrderIntentStock, OptionLeg
from rhx.providers.robin_stocks_unofficial import RobinStocksProvider


class FakeAuth:
    @contextmanager
    def external_output_guard(self):
        yield

    def ensure_brokerage_authenticated(self, interactive: bool = False, force: bool = False):
        del interactive, force
        return None

    def brokerage_status(self):
        return None


class FakeRH:
    def __init__(self):
        self.called: list[str] = []
        self.symbol_by_url: dict[str, str | Exception | None] = {}
        self.symbol_lookup_calls: list[str] = []

    def load_account_profile(self):
        return {"account": "a"}

    def load_portfolio_profile(self):
        return {"portfolio": "p"}

    def load_user_profile(self):
        return {"user": "u"}

    def get_open_stock_positions(self):
        return [{"symbol": "AAPL"}]

    def get_crypto_positions(self):
        return [{"currency": "BTC"}]

    def get_open_option_positions(self):
        return [{"option": "AAPL_2026"}]

    def get_crypto_quote(self, symbol):
        self.called.append("get_crypto_quote")
        return {"symbol": symbol}

    def get_quotes(self, symbol):
        self.called.append("get_quotes")
        return [{"symbol": symbol}]

    def get_symbol_by_url(self, url):
        self.symbol_lookup_calls.append(url)
        value = self.symbol_by_url.get(url)
        if isinstance(value, Exception):
            raise value
        return value

    def order_buy_market(self, *args, **kwargs):
        self.called.append("order_buy_market")
        return {"id": "m1", "state": "queued"}

    def order_sell_market(self, *args, **kwargs):
        self.called.append("order_sell_market")
        return {"id": "m2", "state": "queued"}

    def order_buy_fractional_by_price(self, *args, **kwargs):
        self.called.append("order_buy_fractional_by_price")
        return {"id": "m3", "state": "queued"}

    def order_sell_fractional_by_price(self, *args, **kwargs):
        self.called.append("order_sell_fractional_by_price")
        return {"id": "m4", "state": "queued"}

    def order_buy_limit(self, *args, **kwargs):
        self.called.append("order_buy_limit")
        return {"id": "l1", "state": "queued"}

    def order_sell_limit(self, *args, **kwargs):
        self.called.append("order_sell_limit")
        return {"id": "l2", "state": "queued"}

    def order_buy_stop_limit(self, *args, **kwargs):
        self.called.append("order_buy_stop_limit")
        return {"id": "s1", "state": "queued"}

    def order_sell_stop_limit(self, *args, **kwargs):
        self.called.append("order_sell_stop_limit")
        return {"id": "s2", "state": "queued"}

    def order_buy_crypto_by_price(self, *args, **kwargs):
        self.called.append("order_buy_crypto_by_price")
        return {"id": "c1", "state": "queued"}

    def order_sell_crypto_by_price(self, *args, **kwargs):
        self.called.append("order_sell_crypto_by_price")
        return {"id": "c2", "state": "queued"}

    def order_buy_crypto_by_quantity(self, *args, **kwargs):
        self.called.append("order_buy_crypto_by_quantity")
        return {"id": "c3", "state": "queued"}

    def order_sell_crypto_by_quantity(self, *args, **kwargs):
        self.called.append("order_sell_crypto_by_quantity")
        return {"id": "c4", "state": "queued"}

    def order_buy_crypto_limit(self, *args, **kwargs):
        self.called.append("order_buy_crypto_limit")
        return {"id": "c5", "state": "queued"}

    def order_sell_crypto_limit(self, *args, **kwargs):
        self.called.append("order_sell_crypto_limit")
        return {"id": "c6", "state": "queued"}

    def order_buy_crypto_limit_by_price(self, *args, **kwargs):
        self.called.append("order_buy_crypto_limit_by_price")
        return {"id": "c7", "state": "queued"}

    def order_sell_crypto_limit_by_price(self, *args, **kwargs):
        self.called.append("order_sell_crypto_limit_by_price")
        return {"id": "c8", "state": "queued"}

    def order_buy_option_limit(self, **kwargs):
        del kwargs
        self.called.append("order_buy_option_limit")
        return {"id": "o1", "state": "queued"}

    def order_buy_option_stop_limit(self, **kwargs):
        del kwargs
        self.called.append("order_buy_option_stop_limit")
        return {"id": "o2", "state": "queued"}

    def order_sell_option_limit(self, **kwargs):
        del kwargs
        self.called.append("order_sell_option_limit")
        return {"id": "o3", "state": "queued"}

    def order_sell_option_stop_limit(self, **kwargs):
        del kwargs
        self.called.append("order_sell_option_stop_limit")
        return {"id": "o4", "state": "queued"}

    def order_option_credit_spread(self, **kwargs):
        del kwargs
        self.called.append("order_option_credit_spread")
        return {"id": "os1", "state": "queued"}

    def order_option_debit_spread(self, **kwargs):
        del kwargs
        self.called.append("order_option_debit_spread")
        return {"id": "os2", "state": "queued"}

    def cancel_stock_order(self, order_id):
        return {"cancelled": order_id}

    def cancel_option_order(self, order_id):
        return {"cancelled": order_id}

    def cancel_crypto_order(self, order_id):
        return {"cancelled": order_id}

    def get_stock_order_info(self, order_id):
        return {"id": order_id}

    def get_option_order_info(self, order_id):
        return {"id": order_id}

    def get_crypto_order_info(self, order_id):
        return {"id": order_id}

    def get_all_stock_orders(self):
        return [{"id": "s"}]

    def get_all_open_stock_orders(self):
        return [{"id": "so"}]

    def get_all_option_orders(self):
        return [{"id": "o"}]

    def get_all_open_option_orders(self):
        return [{"id": "oo"}]

    def get_all_crypto_orders(self):
        return [{"id": "c"}]

    def get_all_open_crypto_orders(self):
        return [{"id": "co"}]

    def get_chains(self, symbol):
        return {"symbol": symbol}

    def find_options_by_expiration_and_strike(self, *args, **kwargs):
        return [{"branch": "expiration+strike"}]

    def find_options_by_expiration(self, *args, **kwargs):
        return [{"branch": "expiration"}]

    def find_options_by_strike(self, *args, **kwargs):
        return [{"branch": "strike"}]

    def find_tradable_options(self, *args, **kwargs):
        return [{"branch": "all"}]


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch):
    fake_rh = FakeRH()
    monkeypatch.setattr(RobinStocksProvider, "_load_rh", lambda self: fake_rh)
    p = RobinStocksProvider(auth=FakeAuth())
    return p, fake_rh


def test_summary_positions_quote(provider):
    p, _ = provider
    assert "account_profile" in p.account_summary()
    pos = p.positions()
    assert {x["asset_type"] for x in pos} == {"stock", "crypto", "option"}
    assert p.quote("AAPL")["asset_type"] == "stock"
    assert p.quote("BTC-USD")["asset_type"] == "crypto"


def test_stock_order_mappings(provider):
    p, fake_rh = provider

    p.place_order(OrderIntentStock(symbol="AAPL", side="buy", order_type="market", quantity=1))
    p.place_order(OrderIntentStock(symbol="AAPL", side="sell", order_type="market", quantity=1))
    p.place_order(OrderIntentStock(symbol="AAPL", side="buy", order_type="market", notional_usd=10))
    p.place_order(OrderIntentStock(symbol="AAPL", side="sell", order_type="market", notional_usd=10))
    p.place_order(OrderIntentStock(symbol="AAPL", side="buy", order_type="limit", quantity=1, limit_price=100))
    p.place_order(OrderIntentStock(symbol="AAPL", side="sell", order_type="limit", quantity=1, limit_price=100))
    p.place_order(OrderIntentStock(symbol="AAPL", side="buy", order_type="stop_limit", quantity=1, limit_price=100, stop_price=99))
    p.place_order(OrderIntentStock(symbol="AAPL", side="sell", order_type="stop_limit", quantity=1, limit_price=100, stop_price=99))

    assert "order_buy_market" in fake_rh.called
    assert "order_sell_market" in fake_rh.called
    assert "order_buy_fractional_by_price" in fake_rh.called
    assert "order_sell_fractional_by_price" in fake_rh.called
    assert "order_buy_limit" in fake_rh.called
    assert "order_sell_limit" in fake_rh.called
    assert "order_buy_stop_limit" in fake_rh.called
    assert "order_sell_stop_limit" in fake_rh.called


def test_stock_notional_non_market_rejected(provider):
    p, _ = provider
    with pytest.raises(CLIError) as exc:
        p.place_order(OrderIntentStock(symbol="AAPL", side="buy", order_type="limit", quantity=1, limit_price=100, notional_usd=10))
    assert exc.value.code == ErrorCode.VALIDATION_ERROR


def test_crypto_order_mappings(provider):
    p, fake_rh = provider
    p.place_order(OrderIntentCrypto(symbol="BTC-USD", side="buy", order_type="market", amount_in="quantity", quantity=1))
    p.place_order(OrderIntentCrypto(symbol="BTC-USD", side="sell", order_type="market", amount_in="quantity", quantity=1))
    p.place_order(OrderIntentCrypto(symbol="BTC-USD", side="buy", order_type="market", amount_in="price", notional_usd=10))
    p.place_order(OrderIntentCrypto(symbol="BTC-USD", side="sell", order_type="market", amount_in="price", notional_usd=10))
    p.place_order(OrderIntentCrypto(symbol="BTC-USD", side="buy", order_type="limit", amount_in="quantity", quantity=1, limit_price=100))
    p.place_order(OrderIntentCrypto(symbol="BTC-USD", side="sell", order_type="limit", amount_in="quantity", quantity=1, limit_price=100))
    p.place_order(OrderIntentCrypto(symbol="BTC-USD", side="buy", order_type="limit", amount_in="price", notional_usd=10, limit_price=100))
    p.place_order(OrderIntentCrypto(symbol="BTC-USD", side="sell", order_type="limit", amount_in="price", notional_usd=10, limit_price=100))

    assert "order_buy_crypto_by_quantity" in fake_rh.called
    assert "order_sell_crypto_by_quantity" in fake_rh.called
    assert "order_buy_crypto_by_price" in fake_rh.called
    assert "order_sell_crypto_by_price" in fake_rh.called
    assert "order_buy_crypto_limit" in fake_rh.called
    assert "order_sell_crypto_limit" in fake_rh.called
    assert "order_buy_crypto_limit_by_price" in fake_rh.called
    assert "order_sell_crypto_limit_by_price" in fake_rh.called


def test_option_mappings_and_find_branches(provider):
    p, fake_rh = provider

    p.place_order(
        OrderIntentOptionSingle(
            side="buy",
            order_type="stop_limit",
            position_effect="open",
            credit_or_debit="debit",
            symbol="AAPL",
            quantity=1,
            expiration_date="2026-12-18",
            strike=200,
            option_type="call",
            limit_price=1,
            stop_price=1,
        )
    )
    p.place_order(
        OrderIntentOptionSingle(
            side="sell",
            order_type="limit",
            position_effect="close",
            credit_or_debit="credit",
            symbol="AAPL",
            quantity=1,
            expiration_date="2026-12-18",
            strike=200,
            option_type="call",
            price=1,
        )
    )

    spread = [
        OptionLeg(expirationDate="2026-12-18", strike=200, optionType="call", effect="open", action="sell"),
        OptionLeg(expirationDate="2026-12-18", strike=205, optionType="call", effect="open", action="buy"),
    ]
    p.place_order(OrderIntentOptionSpread(direction="credit", symbol="AAPL", quantity=1, price=1, spread=spread))
    p.place_order(OrderIntentOptionSpread(direction="debit", symbol="AAPL", quantity=1, price=1, spread=spread))

    assert "order_buy_option_stop_limit" in fake_rh.called
    assert "order_sell_option_limit" in fake_rh.called
    assert "order_option_credit_spread" in fake_rh.called
    assert "order_option_debit_spread" in fake_rh.called

    assert p.option_contracts_find("AAPL", expiration_date="2026-12-18", strike_price=200)[0]["branch"] == "expiration+strike"
    assert p.option_contracts_find("AAPL", expiration_date="2026-12-18")[0]["branch"] == "expiration"
    assert p.option_contracts_find("AAPL", strike_price=200)[0]["branch"] == "strike"
    assert p.option_contracts_find("AAPL")[0]["branch"] == "all"


def test_cancel_get_and_list_orders(provider):
    p, _ = provider

    assert p.cancel_order("x", asset_type="stock")["asset_type"] == "stock"
    assert p.get_order("x", asset_type="option")["asset_type"] == "option"
    assert len(p.list_orders(open_only=False)) == 3
    assert len(p.list_orders(open_only=True)) == 3
    assert p.option_chains("AAPL")["symbol"] == "AAPL"


def test_cancel_get_errors_when_all_handlers_fail(provider):
    p, _ = provider

    p._rh.cancel_stock_order = lambda order_id: (_ for _ in ()).throw(RuntimeError("s"))
    p._rh.cancel_option_order = lambda order_id: (_ for _ in ()).throw(RuntimeError("o"))
    p._rh.cancel_crypto_order = lambda order_id: (_ for _ in ()).throw(RuntimeError("c"))

    with pytest.raises(CLIError) as cancel_exc:
        p.cancel_order("x")
    assert cancel_exc.value.code == ErrorCode.BROKER_REJECTED

    p._rh.get_stock_order_info = lambda order_id: (_ for _ in ()).throw(RuntimeError("s"))
    p._rh.get_option_order_info = lambda order_id: (_ for _ in ()).throw(RuntimeError("o"))
    p._rh.get_crypto_order_info = lambda order_id: (_ for _ in ()).throw(RuntimeError("c"))

    with pytest.raises(CLIError) as get_exc:
        p.get_order("x")
    assert get_exc.value.code == ErrorCode.BROKER_REJECTED


def test_list_orders_symbol_hydration_resolves_and_caches(provider):
    p, fake_rh = provider
    url_one = "https://api.robinhood.com/instruments/1/"
    url_two = "https://api.robinhood.com/instruments/2/"

    fake_rh.symbol_by_url = {
        url_one: "VOO",
        url_two: "AAPL",
    }
    fake_rh.get_all_stock_orders = lambda: [
        {"id": "s1", "instrument": url_one},
        {"id": "s2", "instrument": url_one, "symbol": None},
        {"id": "s3", "instrument": url_two, "symbol": ""},
    ]

    rows = p.list_orders(open_only=False, asset_type="stock", symbol_resolve_limit=10)
    assert rows[0]["symbol"] == "VOO"
    assert rows[1]["symbol"] == "VOO"
    assert rows[2]["symbol"] == "AAPL"
    assert fake_rh.symbol_lookup_calls.count(url_one) == 1
    assert fake_rh.symbol_lookup_calls.count(url_two) == 1


def test_list_orders_symbol_hydration_respects_limit(provider):
    p, fake_rh = provider
    url_one = "https://api.robinhood.com/instruments/1/"
    url_two = "https://api.robinhood.com/instruments/2/"
    url_three = "https://api.robinhood.com/instruments/3/"

    fake_rh.symbol_by_url = {
        url_one: "VOO",
        url_two: "AAPL",
        url_three: "MSFT",
    }
    fake_rh.get_all_stock_orders = lambda: [
        {"id": "s1", "instrument": url_one},
        {"id": "s2", "instrument": url_two},
        {"id": "s3", "instrument": url_three},
    ]

    rows = p.list_orders(open_only=False, asset_type="stock", symbol_resolve_limit=1)
    assert rows[0]["symbol"] == "VOO"
    assert rows[1].get("symbol") is None
    assert rows[2].get("symbol") is None
    assert len(fake_rh.symbol_lookup_calls) == 1


def test_list_orders_symbol_hydration_default_limit_is_bounded(provider):
    p, fake_rh = provider
    stock_rows = []
    for idx in range(205):
        url = f"https://api.robinhood.com/instruments/{idx}/"
        stock_rows.append({"id": str(idx), "instrument": url})
        fake_rh.symbol_by_url[url] = f"S{idx}"

    fake_rh.get_all_stock_orders = lambda: stock_rows
    rows = p.list_orders(open_only=False, asset_type="stock")

    assert len(fake_rh.symbol_lookup_calls) == 200
    assert rows[199]["symbol"] == "S199"
    assert rows[200].get("symbol") is None


def test_list_orders_symbol_hydration_is_best_effort(provider):
    p, fake_rh = provider
    url_one = "https://api.robinhood.com/instruments/1/"
    fake_rh.symbol_by_url = {url_one: RuntimeError("lookup failed")}
    fake_rh.get_all_stock_orders = lambda: [{"id": "s1", "instrument": url_one}]

    rows = p.list_orders(open_only=False, asset_type="stock", symbol_resolve_limit=10)
    assert rows[0].get("symbol") is None
    assert fake_rh.symbol_lookup_calls == [url_one]
