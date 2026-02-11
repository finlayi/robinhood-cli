from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class CapabilitySet(BaseModel):
    stocks: bool = False
    crypto: bool = False
    options: bool = False
    options_spreads: bool = False


class AuthStatus(BaseModel):
    provider: str
    authenticated: bool
    mfa_required: bool = False
    detail: str | None = None


class BrokeragePassiveStatus(BaseModel):
    session_pickle_exists: bool
    credentials_present: bool
    session_ready: bool
    detail: str


class OptionQuoteRecord(BaseModel):
    contract_id: str | None = None
    symbol: str
    expiration_date: str
    strike_price: float
    option_type: Literal["call", "put"]
    bid_price: str | None = None
    ask_price: str | None = None
    mark_price: str | None = None
    last_trade_price: str | None = None
    implied_volatility: str | None = None
    delta: str | None = None
    gamma: str | None = None
    theta: str | None = None
    vega: str | None = None
    rho: str | None = None
    open_interest: str | None = None
    volume: str | None = None
    updated_at: str | None = None
    tradability: str | None = None
    state: str | None = None


class PortfolioHolding(BaseModel):
    symbol: str
    asset_type: str
    quantity: float
    last_price: float | None = None
    market_value: float | None = None
    weight_pct: float | None = None
    cost_basis: float | None = None
    unrealized_pnl: float | None = None
    unrealized_pnl_pct: float | None = None


class PortfolioAnalysisResult(BaseModel):
    account: dict[str, Any]
    allocation: list[PortfolioHolding]
    concentration: dict[str, Any]
    exposure: dict[str, Any]
    alerts: list[dict[str, Any]]
    generated_at: str


class OptionLeg(BaseModel):
    expirationDate: str
    strike: float
    optionType: Literal["call", "put"]
    effect: Literal["open", "close"]
    action: Literal["buy", "sell"]


class OrderIntentStock(BaseModel):
    asset_type: Literal["stock"] = "stock"
    symbol: str
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit", "stop_limit"] = "market"
    quantity: float | None = None
    notional_usd: float | None = None
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: Literal["gtc", "gfd", "ioc", "fok", "opg"] = "gtc"
    extended_hours: bool = False

    @model_validator(mode="after")
    def validate_order(self) -> "OrderIntentStock":
        if self.quantity is None and self.notional_usd is None:
            raise ValueError("Either quantity or notional_usd is required")
        if self.order_type == "limit" and self.limit_price is None:
            raise ValueError("limit_price is required for limit orders")
        if self.order_type == "stop_limit" and (self.limit_price is None or self.stop_price is None):
            raise ValueError("limit_price and stop_price are required for stop_limit orders")
        return self


class OrderIntentCrypto(BaseModel):
    asset_type: Literal["crypto"] = "crypto"
    symbol: str
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit"] = "market"
    amount_in: Literal["quantity", "price"] = "quantity"
    quantity: float | None = None
    notional_usd: float | None = None
    limit_price: float | None = None
    time_in_force: Literal["gtc", "gfd", "ioc", "fok"] = "gtc"

    @model_validator(mode="after")
    def validate_order(self) -> "OrderIntentCrypto":
        if self.amount_in == "quantity" and self.quantity is None:
            raise ValueError("quantity is required when amount_in=quantity")
        if self.amount_in == "price" and self.notional_usd is None:
            raise ValueError("notional_usd is required when amount_in=price")
        if self.order_type == "limit" and self.limit_price is None:
            raise ValueError("limit_price is required for limit orders")
        return self


class OrderIntentOptionSingle(BaseModel):
    asset_type: Literal["option_single"] = "option_single"
    side: Literal["buy", "sell"]
    order_type: Literal["limit", "stop_limit"] = "limit"
    position_effect: Literal["open", "close"]
    credit_or_debit: Literal["credit", "debit"]
    symbol: str
    quantity: int = Field(ge=1)
    expiration_date: str
    strike: float
    option_type: Literal["call", "put", "both"] = "both"
    price: float | None = None
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: Literal["gtc", "gfd", "ioc", "fok", "opg"] = "gtc"

    @model_validator(mode="after")
    def validate_order(self) -> "OrderIntentOptionSingle":
        if self.order_type == "limit" and self.price is None:
            raise ValueError("price is required for limit option orders")
        if self.order_type == "stop_limit" and (self.limit_price is None or self.stop_price is None):
            raise ValueError("limit_price and stop_price are required for stop_limit option orders")
        return self


class OrderIntentOptionSpread(BaseModel):
    asset_type: Literal["option_spread"] = "option_spread"
    direction: Literal["credit", "debit"]
    symbol: str
    quantity: int = Field(ge=1)
    price: float = Field(gt=0)
    spread: list[OptionLeg] = Field(min_length=2)
    time_in_force: Literal["gtc", "gfd", "ioc", "fok", "opg"] = "gtc"


class OrderResult(BaseModel):
    provider: str
    order_id: str | None = None
    state: str | None = None
    symbol: str | None = None
    side: str | None = None
    asset_type: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class BrokerError(BaseModel):
    code: str
    message: str
    retriable: bool = False
    details: dict[str, Any] | None = None


class OutputEnvelope(BaseModel):
    ok: bool
    command: str
    provider: str | None = None
    data: dict[str, Any] | list[Any] | None = None
    error: BrokerError | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def success(
        cls,
        command: str,
        data: dict[str, Any] | list[Any] | None,
        provider: str | None = None,
    ) -> "OutputEnvelope":
        return cls(
            ok=True,
            command=command,
            provider=provider,
            data=data,
            meta={"timestamp": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")},
        )

    @classmethod
    def failure(
        cls,
        command: str,
        code: str,
        message: str,
        retriable: bool = False,
        provider: str | None = None,
    ) -> "OutputEnvelope":
        return cls(
            ok=False,
            command=command,
            provider=provider,
            error=BrokerError(code=code, message=message, retriable=retriable),
            meta={"timestamp": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")},
        )
