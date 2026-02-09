from __future__ import annotations

import pytest

from rhx.models import OrderIntentOptionSingle, OrderIntentOptionSpread, OptionLeg
from rhx.providers.robin_stocks_unofficial import RobinStocksProvider


class FakeAuth:
    def ensure_brokerage_authenticated(self, interactive: bool = False, force: bool = False):
        del interactive, force
        return None

    def brokerage_status(self):
        return None


class FakeRH:
    def __init__(self):
        self.called: list[str] = []

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
        return {"id": "s1", "state": "queued"}

    def order_option_debit_spread(self, **kwargs):
        del kwargs
        self.called.append("order_option_debit_spread")
        return {"id": "s2", "state": "queued"}


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch):
    fake_rh = FakeRH()
    monkeypatch.setattr(RobinStocksProvider, "_load_rh", lambda self: fake_rh)
    p = RobinStocksProvider(auth=FakeAuth())
    return p, fake_rh


def test_option_single_mapping(provider):
    p, fake_rh = provider
    intent = OrderIntentOptionSingle(
        side="buy",
        order_type="limit",
        position_effect="open",
        credit_or_debit="debit",
        symbol="AAPL",
        quantity=1,
        expiration_date="2026-12-18",
        strike=200,
        option_type="call",
        price=1.23,
    )

    p.place_order(intent)
    assert fake_rh.called[-1] == "order_buy_option_limit"


def test_option_spread_mapping(provider):
    p, fake_rh = provider
    spread = [
        OptionLeg(expirationDate="2026-12-18", strike=200, optionType="call", effect="open", action="sell"),
        OptionLeg(expirationDate="2026-12-18", strike=205, optionType="call", effect="open", action="buy"),
    ]

    credit = OrderIntentOptionSpread(direction="credit", symbol="AAPL", quantity=1, price=1.0, spread=spread)
    debit = OrderIntentOptionSpread(direction="debit", symbol="AAPL", quantity=1, price=1.0, spread=spread)

    p.place_order(credit)
    p.place_order(debit)

    assert "order_option_credit_spread" in fake_rh.called
    assert "order_option_debit_spread" in fake_rh.called
