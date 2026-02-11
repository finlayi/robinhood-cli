from __future__ import annotations

import pytest

from rhx.errors import CLIError, ErrorCode
from rhx.output_shape import shape_data


def test_shape_positions_summary_limit_and_meta():
    data = [
        {
            "asset_type": "crypto",
            "currency": {"code": "USDC"},
            "id": "p1",
            "quantity": "1.0",
            "cost_bases": [{"direct_cost_basis": "0.99"}],
            "updated_at": "2026-02-08T17:28:49Z",
        },
        {
            "asset_type": "stock",
            "symbol": "AAPL",
            "id": "p2",
            "quantity": "2.0",
        },
    ]

    shaped, meta = shape_data(
        command="positions list",
        provider="brokerage",
        data=data,
        view="summary",
        fields=None,
        limit=1,
    )

    assert isinstance(shaped, list)
    assert len(shaped) == 1
    assert list(shaped[0].keys()) == [
        "asset_type",
        "symbol",
        "position_id",
        "quantity",
        "quantity_available",
        "quantity_held",
        "cost_basis",
        "market_value",
        "average_buy_price",
        "updated_at",
    ]
    assert shaped[0]["symbol"] == "USDC"
    assert shaped[0]["position_id"] == "p1"
    assert shaped[0]["cost_basis"] == "0.99"
    assert meta["total_count"] == 2
    assert meta["returned_count"] == 1
    assert meta["truncated"] is True


def test_shape_summary_fields_projection_and_unknown_field_rejected():
    data = [{"asset_type": "stock", "symbol": "AAPL", "id": "p1", "quantity": "1.0"}]

    shaped, meta = shape_data(
        command="positions list",
        provider="brokerage",
        data=data,
        view="summary",
        fields=["symbol", "quantity"],
        limit=None,
    )

    assert shaped == [{"symbol": "AAPL", "quantity": "1.0"}]
    assert meta["fields"] == ["symbol", "quantity"]

    with pytest.raises(CLIError) as exc:
        shape_data(
            command="positions list",
            provider="brokerage",
            data=data,
            view="summary",
            fields=["symbol", "bad_field"],
            limit=None,
        )
    assert "Unknown field(s)" in str(exc.value)


def test_shape_full_passthrough_and_rejects_fields():
    data = [{"id": "1", "raw": {"nested": True}}]

    shaped, meta = shape_data(
        command="orders list",
        provider="brokerage",
        data=data,
        view="full",
        fields=None,
        limit=None,
    )
    assert shaped == data
    assert meta["total_count"] == 1
    assert meta["returned_count"] == 1
    assert meta["truncated"] is False

    with pytest.raises(CLIError) as exc:
        shape_data(
            command="orders list",
            provider="brokerage",
            data=data,
            view="full",
            fields=["order_id"],
            limit=None,
        )
    assert "requires --view summary" in str(exc.value)


def test_shape_quote_infers_asset_type_and_order_summary_excludes_raw():
    quote_shaped, _ = shape_data(
        command="quote get",
        provider="brokerage",
        data={"symbol": "AAPL", "quote": {"bid": "1.0", "ask": "2.0", "price": "1.5"}},
        view="summary",
        fields=None,
        limit=None,
    )
    assert quote_shaped["asset_type"] == "stock"
    assert quote_shaped["bid_price"] == "1.0"

    order_shaped, _ = shape_data(
        command="orders stock place",
        provider="brokerage",
        data={
            "asset_type": "stock",
            "order_id": "ord-1",
            "symbol": "AAPL",
            "side": "buy",
            "state": "queued",
            "raw": {"id": "legacy"},
        },
        view="summary",
        fields=None,
        limit=None,
    )
    assert "raw" not in order_shaped
    assert order_shaped["order_id"] == "ord-1"


def test_shape_invalid_view_raises_validation_error():
    with pytest.raises(CLIError) as exc:
        shape_data(
            command="quote get",
            provider="brokerage",
            data={"symbol": "AAPL"},
            view="unknown",
            fields=None,
            limit=None,
        )
    assert "Unsupported --view" in str(exc.value)
    assert exc.value.code == ErrorCode.VALIDATION_ERROR


def test_shape_orders_list_preserves_hydrated_symbol():
    shaped, _ = shape_data(
        command="orders list",
        provider="brokerage",
        data=[{"asset_type": "stock", "id": "ord-1", "symbol": "VOO", "state": "filled"}],
        view="summary",
        fields=None,
        limit=None,
    )
    assert shaped[0]["symbol"] == "VOO"


def test_shape_quote_list_summary_fields():
    shaped, meta = shape_data(
        command="quote list",
        provider="brokerage",
        data=[
            {
                "symbol": "AAPL",
                "asset_type": "stock",
                "provider": "brokerage",
                "bid_price": "1.0",
                "ask_price": "1.2",
                "mark_price": "1.1",
                "last_trade_price": "1.1",
                "updated_at": "2026-02-11T00:00:00Z",
                "error": None,
            }
        ],
        view="summary",
        fields=None,
        limit=None,
    )
    assert shaped[0]["symbol"] == "AAPL"
    assert shaped[0]["provider"] == "brokerage"
    assert shaped[0]["error"] is None
    assert meta["total_count"] == 1


def test_shape_options_expirations_and_strikes_summaries():
    exp_shaped, _ = shape_data(
        command="options expirations",
        provider="brokerage",
        data={"symbol": "AAPL", "expiration_dates": ["2026-12-18", "2027-01-15"]},
        view="summary",
        fields=None,
        limit=None,
    )
    assert exp_shaped["expiration_count"] == 2
    assert exp_shaped["next_expiration"] == "2026-12-18"
    assert exp_shaped["last_expiration"] == "2027-01-15"

    strikes_shaped, _ = shape_data(
        command="options strikes",
        provider="brokerage",
        data={"symbol": "AAPL", "expiration_date": "2026-12-18", "option_type": "call", "strikes": [90, 100, 110]},
        view="summary",
        fields=None,
        limit=None,
    )
    assert strikes_shaped["strike_count"] == 3
    assert strikes_shaped["min_strike"] == 90.0
    assert strikes_shaped["max_strike"] == 110.0


def test_shape_option_quote_and_portfolio_analyze():
    option_shaped, _ = shape_data(
        command="options quotes get",
        provider="brokerage",
        data={
            "contract_id": "id-1",
            "symbol": "AAPL",
            "expiration_date": "2026-12-18",
            "strike_price": 100.0,
            "option_type": "call",
            "bid_price": "1.0",
            "ask_price": "1.2",
            "delta": "0.5",
            "open_interest": "100",
        },
        view="summary",
        fields=None,
        limit=None,
    )
    assert option_shaped["contract_id"] == "id-1"
    assert option_shaped["delta"] == "0.5"

    portfolio_shaped, _ = shape_data(
        command="portfolio analyze",
        provider="brokerage",
        data={
            "account": {"equity": 1000},
            "allocation": [{"symbol": "AAPL"}],
            "concentration": {"largest_position_pct": 80},
            "exposure": {"by_asset_type": {"stock": {"market_value": 1000}}},
            "alerts": [{"code": "TOP3_CONCENTRATION"}],
            "generated_at": "2026-02-11T00:00:00Z",
        },
        view="summary",
        fields=["account", "alerts"],
        limit=None,
    )
    assert portfolio_shaped == {"account": {"equity": 1000}, "alerts": [{"code": "TOP3_CONCENTRATION"}]}
