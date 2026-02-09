from __future__ import annotations

import pytest
from pydantic import ValidationError

from rhx.models import OrderIntentCrypto, OrderIntentOptionSingle, OrderIntentStock, OutputEnvelope


def test_stock_and_crypto_validation_errors():
    with pytest.raises(ValidationError):
        OrderIntentStock(symbol="AAPL", side="buy", order_type="market")

    with pytest.raises(ValidationError):
        OrderIntentStock(symbol="AAPL", side="buy", order_type="limit", quantity=1)

    with pytest.raises(ValidationError):
        OrderIntentCrypto(symbol="BTC-USD", side="buy", order_type="market", amount_in="quantity")

    with pytest.raises(ValidationError):
        OrderIntentCrypto(symbol="BTC-USD", side="buy", order_type="limit", amount_in="price", notional_usd=10)


def test_option_single_validation_errors_and_output_failure():
    with pytest.raises(ValidationError):
        OrderIntentOptionSingle(
            side="buy",
            order_type="limit",
            position_effect="open",
            credit_or_debit="debit",
            symbol="AAPL",
            quantity=1,
            expiration_date="2026-12-18",
            strike=200,
        )

    with pytest.raises(ValidationError):
        OrderIntentOptionSingle(
            side="buy",
            order_type="stop_limit",
            position_effect="open",
            credit_or_debit="debit",
            symbol="AAPL",
            quantity=1,
            expiration_date="2026-12-18",
            strike=200,
            limit_price=1.0,
        )

    fail = OutputEnvelope.failure("cmd", code="ERR", message="nope")
    assert fail.ok is False
    assert fail.error is not None
