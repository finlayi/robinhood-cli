from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TypeAlias

from rhx.errors import CLIError, ErrorCode


PathPart: TypeAlias = str | int
CandidatePath: TypeAlias = tuple[PathPart, ...]
SummaryFn: TypeAlias = Callable[[Any, str | None], Any]


@dataclass(frozen=True)
class SummarySpec:
    fields: tuple[str, ...]
    summarize: SummaryFn


def _path(*parts: PathPart) -> CandidatePath:
    return parts


def _get_path(data: Any, path: CandidatePath) -> Any:
    current = data
    for part in path:
        if isinstance(part, int):
            if not isinstance(current, list):
                return None
            if part < 0 or part >= len(current):
                return None
            current = current[part]
            continue

        if not isinstance(current, dict):
            return None
        if part not in current:
            return None
        current = current[part]
    return current


def _first(payload: dict[str, Any], candidates: tuple[CandidatePath, ...]) -> Any:
    for candidate in candidates:
        value = _get_path(payload, candidate)
        if value is not None:
            return value
    return None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _normalize_object(
    data: Any,
    field_order: tuple[str, ...],
    candidates_by_field: dict[str, tuple[CandidatePath, ...]],
) -> dict[str, Any]:
    payload = _as_dict(data)
    return {field: _first(payload, candidates_by_field.get(field, ())) for field in field_order}


def _normalize_list(
    data: Any,
    field_order: tuple[str, ...],
    candidates_by_field: dict[str, tuple[CandidatePath, ...]],
) -> list[dict[str, Any]]:
    return [_normalize_object(row, field_order, candidates_by_field) for row in _as_list(data)]


def _project_fields(data: Any, fields: list[str]) -> Any:
    if isinstance(data, dict):
        return {field: data.get(field) for field in fields}
    if isinstance(data, list):
        projected: list[Any] = []
        for row in data:
            if isinstance(row, dict):
                projected.append({field: row.get(field) for field in fields})
            else:
                projected.append(row)
        return projected
    return data


def _summarize_identity(data: Any, provider: str | None) -> Any:
    del provider
    return data


ACCOUNT_SUMMARY_FIELDS = (
    "account_id",
    "account_type",
    "cash",
    "buying_power",
    "withdrawable_amount",
    "portfolio_equity",
    "market_value",
    "total_value",
    "updated_at",
)
ACCOUNT_SUMMARY_PATHS: dict[str, tuple[CandidatePath, ...]] = {
    "account_id": (
        _path("account_profile", "account_number"),
        _path("account_profile", "id"),
        _path("account_id"),
        _path("id"),
    ),
    "account_type": (
        _path("account_profile", "type"),
        _path("account_profile", "account_type"),
        _path("account_type"),
        _path("type"),
    ),
    "cash": (
        _path("account_profile", "cash"),
        _path("account_profile", "cash_available_for_withdrawal"),
        _path("portfolio_profile", "cash"),
        _path("cash"),
    ),
    "buying_power": (
        _path("account_profile", "buying_power"),
        _path("portfolio_profile", "buying_power"),
        _path("buying_power"),
    ),
    "withdrawable_amount": (
        _path("account_profile", "cash_available_for_withdrawal"),
        _path("account_profile", "withdrawable_amount"),
        _path("withdrawable_amount"),
    ),
    "portfolio_equity": (
        _path("portfolio_profile", "equity"),
        _path("portfolio_equity"),
        _path("equity"),
    ),
    "market_value": (
        _path("portfolio_profile", "market_value"),
        _path("market_value"),
    ),
    "total_value": (
        _path("portfolio_profile", "extended_hours_equity"),
        _path("portfolio_profile", "equity"),
        _path("total_value"),
        _path("equity"),
    ),
    "updated_at": (
        _path("portfolio_profile", "updated_at"),
        _path("account_profile", "updated_at"),
        _path("updated_at"),
    ),
}


def _summarize_account_summary(data: Any, provider: str | None) -> dict[str, Any]:
    del provider
    return _normalize_object(data, ACCOUNT_SUMMARY_FIELDS, ACCOUNT_SUMMARY_PATHS)


POSITIONS_FIELDS = (
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
)
POSITIONS_PATHS: dict[str, tuple[CandidatePath, ...]] = {
    "asset_type": (
        _path("asset_type"),
        _path("type"),
    ),
    "symbol": (
        _path("symbol"),
        _path("instrument", "symbol"),
        _path("currency", "code"),
        _path("currency", "display_code"),
        _path("code"),
    ),
    "position_id": (
        _path("position_id"),
        _path("id"),
    ),
    "quantity": (
        _path("quantity"),
    ),
    "quantity_available": (
        _path("quantity_available"),
    ),
    "quantity_held": (
        _path("quantity_held"),
    ),
    "cost_basis": (
        _path("cost_basis"),
        _path("average_buy_price"),
        _path("cost_bases", 0, "direct_cost_basis"),
        _path("tax_lot_cost_bases", 0, "clearing_book_cost_basis"),
    ),
    "market_value": (
        _path("market_value"),
        _path("market_value_amount"),
    ),
    "average_buy_price": (
        _path("average_buy_price"),
        _path("cost_bases", 0, "direct_cost_basis"),
    ),
    "updated_at": (
        _path("updated_at"),
    ),
}


def _summarize_positions(data: Any, provider: str | None) -> list[dict[str, Any]]:
    del provider
    return _normalize_list(data, POSITIONS_FIELDS, POSITIONS_PATHS)


QUOTE_FIELDS = (
    "asset_type",
    "symbol",
    "bid_price",
    "ask_price",
    "mark_price",
    "last_trade_price",
    "updated_at",
)
QUOTE_PATHS: dict[str, tuple[CandidatePath, ...]] = {
    "asset_type": (
        _path("asset_type"),
        _path("quote", "asset_type"),
    ),
    "symbol": (
        _path("symbol"),
        _path("quote", "symbol"),
    ),
    "bid_price": (
        _path("quote", "bid_price"),
        _path("quote", "bid"),
        _path("bid_price"),
        _path("bid"),
    ),
    "ask_price": (
        _path("quote", "ask_price"),
        _path("quote", "ask"),
        _path("ask_price"),
        _path("ask"),
    ),
    "mark_price": (
        _path("quote", "mark_price"),
        _path("quote", "price"),
        _path("mark_price"),
        _path("price"),
    ),
    "last_trade_price": (
        _path("quote", "last_trade_price"),
        _path("quote", "price"),
        _path("last_trade_price"),
        _path("price"),
    ),
    "updated_at": (
        _path("quote", "updated_at"),
        _path("quote", "timestamp"),
        _path("updated_at"),
    ),
}


def _summarize_quote(data: Any, provider: str | None) -> dict[str, Any]:
    summary = _normalize_object(data, QUOTE_FIELDS, QUOTE_PATHS)
    if summary["asset_type"] is None and isinstance(summary["symbol"], str):
        symbol = summary["symbol"].upper()
        if "-" in symbol or symbol.endswith("USD"):
            summary["asset_type"] = "crypto"
        elif provider == "brokerage":
            summary["asset_type"] = "stock"
    return summary


ORDER_PLACE_FIELDS = (
    "asset_type",
    "order_id",
    "symbol",
    "side",
    "type",
    "state",
    "quantity",
    "notional_usd",
    "limit_price",
    "submitted_at",
    "updated_at",
)
ORDER_DETAIL_FIELDS = (
    "asset_type",
    "order_id",
    "symbol",
    "side",
    "type",
    "state",
    "quantity",
    "filled_quantity",
    "notional_usd",
    "limit_price",
    "avg_fill_price",
    "submitted_at",
    "updated_at",
)
ORDER_COMMON_PATHS: dict[str, tuple[CandidatePath, ...]] = {
    "asset_type": (
        _path("asset_type"),
        _path("order", "asset_type"),
        _path("raw", "asset_type"),
        _path("order", "type"),
        _path("raw", "type"),
        _path("type"),
    ),
    "order_id": (
        _path("order_id"),
        _path("id"),
        _path("order", "order_id"),
        _path("order", "id"),
        _path("raw", "order_id"),
        _path("raw", "id"),
        _path("result", "order_id"),
        _path("result", "id"),
    ),
    "symbol": (
        _path("symbol"),
        _path("order", "symbol"),
        _path("raw", "symbol"),
        _path("order", "instrument", "symbol"),
        _path("result", "symbol"),
    ),
    "side": (
        _path("side"),
        _path("order", "side"),
        _path("raw", "side"),
    ),
    "type": (
        _path("type"),
        _path("order_type"),
        _path("order", "type"),
        _path("order", "order_type"),
        _path("raw", "type"),
        _path("raw", "order_type"),
    ),
    "state": (
        _path("state"),
        _path("status"),
        _path("detail"),
        _path("order", "state"),
        _path("order", "status"),
        _path("raw", "state"),
        _path("raw", "status"),
        _path("result", "state"),
        _path("result", "status"),
        _path("result", "detail"),
    ),
    "quantity": (
        _path("quantity"),
        _path("order", "quantity"),
        _path("raw", "quantity"),
        _path("raw", "asset_quantity"),
        _path("order", "asset_quantity"),
        _path("raw", "market_order_config", "asset_quantity"),
        _path("raw", "limit_order_config", "asset_quantity"),
    ),
    "notional_usd": (
        _path("notional_usd"),
        _path("notional"),
        _path("quote_amount"),
        _path("order", "notional"),
        _path("order", "quote_amount"),
        _path("raw", "notional"),
        _path("raw", "quote_amount"),
        _path("raw", "market_order_config", "quote_amount"),
        _path("raw", "limit_order_config", "quote_amount"),
    ),
    "limit_price": (
        _path("limit_price"),
        _path("price"),
        _path("order", "limit_price"),
        _path("order", "price"),
        _path("raw", "limit_price"),
        _path("raw", "price"),
        _path("raw", "limit_order_config", "limit_price"),
    ),
    "submitted_at": (
        _path("submitted_at"),
        _path("created_at"),
        _path("order", "submitted_at"),
        _path("order", "created_at"),
        _path("raw", "submitted_at"),
        _path("raw", "created_at"),
        _path("result", "created_at"),
    ),
    "updated_at": (
        _path("updated_at"),
        _path("order", "updated_at"),
        _path("raw", "updated_at"),
        _path("result", "updated_at"),
    ),
    "filled_quantity": (
        _path("filled_quantity"),
        _path("cumulative_quantity"),
        _path("order", "filled_quantity"),
        _path("order", "cumulative_quantity"),
        _path("raw", "filled_quantity"),
        _path("raw", "cumulative_quantity"),
    ),
    "avg_fill_price": (
        _path("avg_fill_price"),
        _path("average_fill_price"),
        _path("average_price"),
        _path("order", "avg_fill_price"),
        _path("order", "average_fill_price"),
        _path("order", "average_price"),
        _path("raw", "avg_fill_price"),
        _path("raw", "average_fill_price"),
        _path("raw", "average_price"),
    ),
}


def _summarize_order_place(data: Any, provider: str | None) -> dict[str, Any]:
    del provider
    return _normalize_object(data, ORDER_PLACE_FIELDS, ORDER_COMMON_PATHS)


def _summarize_order_detail(data: Any, provider: str | None) -> dict[str, Any]:
    del provider
    return _normalize_object(data, ORDER_DETAIL_FIELDS, ORDER_COMMON_PATHS)


def _summarize_order_detail_list(data: Any, provider: str | None) -> list[dict[str, Any]]:
    del provider
    return _normalize_list(data, ORDER_DETAIL_FIELDS, ORDER_COMMON_PATHS)


CANCEL_FIELDS = (
    "asset_type",
    "order_id",
    "cancel_requested",
    "state",
    "detail",
)
CANCEL_PATHS: dict[str, tuple[CandidatePath, ...]] = {
    "asset_type": (
        _path("asset_type"),
        _path("result", "asset_type"),
    ),
    "order_id": (
        _path("order_id"),
        _path("id"),
        _path("result", "order_id"),
        _path("result", "id"),
    ),
    "cancel_requested": (
        _path("cancel_requested"),
        _path("cancelled"),
        _path("result", "cancel_requested"),
        _path("result", "cancelled"),
    ),
    "state": (
        _path("state"),
        _path("status"),
        _path("detail"),
        _path("result", "state"),
        _path("result", "status"),
        _path("result", "detail"),
    ),
    "detail": (
        _path("detail"),
        _path("message"),
        _path("result", "detail"),
        _path("result", "message"),
    ),
}


def _summarize_cancel(data: Any, provider: str | None) -> dict[str, Any]:
    del provider
    payload = _as_dict(data)
    summary = _normalize_object(payload, CANCEL_FIELDS, CANCEL_PATHS)
    cancel_requested = summary.get("cancel_requested")
    if cancel_requested is not None:
        summary["cancel_requested"] = bool(cancel_requested)
    else:
        state = summary.get("state")
        if isinstance(state, str):
            summary["cancel_requested"] = "cancel" in state.lower()
    if summary.get("detail") is None and isinstance(payload.get("result"), str):
        summary["detail"] = payload["result"]
    return summary


OPTIONS_CHAINS_FIELDS = (
    "symbol",
    "chain_id",
    "expiration_count",
    "next_expiration",
    "multiplier",
    "min_tick",
    "tradeable",
)
OPTIONS_CHAINS_PATHS: dict[str, tuple[CandidatePath, ...]] = {
    "symbol": (
        _path("symbol"),
        _path("chain_symbol"),
    ),
    "chain_id": (
        _path("chain_id"),
        _path("id"),
    ),
    "expiration_count": (
        _path("expiration_count"),
    ),
    "next_expiration": (
        _path("next_expiration"),
    ),
    "multiplier": (
        _path("multiplier"),
        _path("trade_value_multiplier"),
    ),
    "min_tick": (
        _path("min_tick"),
    ),
    "tradeable": (
        _path("tradeable"),
    ),
}


def _summarize_options_chains(data: Any, provider: str | None) -> dict[str, Any]:
    del provider
    payload = _as_dict(data)
    summary = _normalize_object(payload, OPTIONS_CHAINS_FIELDS, OPTIONS_CHAINS_PATHS)

    expirations = _first(
        payload,
        (
            _path("expiration_dates"),
            _path("expirations"),
        ),
    )
    if summary["expiration_count"] is None and isinstance(expirations, list):
        summary["expiration_count"] = len(expirations)
    if summary["next_expiration"] is None and isinstance(expirations, list) and expirations:
        summary["next_expiration"] = expirations[0]

    if summary["tradeable"] is None:
        tradability = _first(payload, (_path("tradability"),))
        if isinstance(tradability, str):
            summary["tradeable"] = tradability.lower() == "tradable"

    return summary


OPTION_CONTRACT_FIELDS = (
    "contract_id",
    "symbol",
    "expiration_date",
    "strike_price",
    "option_type",
    "state",
    "tradability",
    "bid_price",
    "ask_price",
    "mark_price",
)
OPTION_CONTRACT_PATHS: dict[str, tuple[CandidatePath, ...]] = {
    "contract_id": (
        _path("contract_id"),
        _path("id"),
    ),
    "symbol": (
        _path("symbol"),
        _path("chain_symbol"),
    ),
    "expiration_date": (
        _path("expiration_date"),
        _path("expiration"),
    ),
    "strike_price": (
        _path("strike_price"),
        _path("strike"),
    ),
    "option_type": (
        _path("option_type"),
        _path("type"),
    ),
    "state": (
        _path("state"),
        _path("status"),
    ),
    "tradability": (
        _path("tradability"),
    ),
    "bid_price": (
        _path("bid_price"),
        _path("bid"),
    ),
    "ask_price": (
        _path("ask_price"),
        _path("ask"),
    ),
    "mark_price": (
        _path("mark_price"),
        _path("mark"),
        _path("price"),
    ),
}


def _summarize_option_contracts(data: Any, provider: str | None) -> list[dict[str, Any]]:
    del provider
    return _normalize_list(data, OPTION_CONTRACT_FIELDS, OPTION_CONTRACT_PATHS)


DOCTOR_FIELDS = (
    "brokerage_authenticated",
    "crypto_authenticated",
    "live_mode",
    "live_unlock_valid",
    "live_unlock_expires_at",
    "provider_default",
    "max_order_notional",
    "max_daily_notional",
    "trading_window",
)
DOCTOR_PATHS: dict[str, tuple[CandidatePath, ...]] = {
    "brokerage_authenticated": (
        _path("auth", "brokerage", "authenticated"),
    ),
    "crypto_authenticated": (
        _path("auth", "crypto", "authenticated"),
    ),
    "live_mode": (
        _path("safety", "live_mode"),
    ),
    "live_unlock_valid": (
        _path("live_unlock", "active"),
    ),
    "live_unlock_expires_at": (
        _path("live_unlock", "expires_at"),
    ),
    "provider_default": (
        _path("provider_default"),
        _path("safety", "provider_default"),
    ),
    "max_order_notional": (
        _path("safety", "max_order_notional"),
    ),
    "max_daily_notional": (
        _path("safety", "max_daily_notional"),
    ),
    "trading_window": (
        _path("safety", "trading_window"),
    ),
}


def _summarize_doctor(data: Any, provider: str | None) -> dict[str, Any]:
    del provider
    return _normalize_object(data, DOCTOR_FIELDS, DOCTOR_PATHS)


SUMMARY_SPECS: dict[str, SummarySpec] = {
    "auth login": SummarySpec(fields=("brokerage", "session_pickle"), summarize=_summarize_identity),
    "auth status": SummarySpec(fields=("brokerage", "crypto"), summarize=_summarize_identity),
    "auth refresh": SummarySpec(fields=("brokerage",), summarize=_summarize_identity),
    "auth logout": SummarySpec(fields=("logged_out", "forget_creds", "session_pickle"), summarize=_summarize_identity),
    "live on": SummarySpec(fields=("live_mode", "live_confirm_token", "expires_at", "ttl_seconds"), summarize=_summarize_identity),
    "live off": SummarySpec(fields=("live_mode",), summarize=_summarize_identity),
    "live status": SummarySpec(fields=("live_mode", "live_unlock"), summarize=_summarize_identity),
    "account summary": SummarySpec(fields=ACCOUNT_SUMMARY_FIELDS, summarize=_summarize_account_summary),
    "positions list": SummarySpec(fields=POSITIONS_FIELDS, summarize=_summarize_positions),
    "quote get": SummarySpec(fields=QUOTE_FIELDS, summarize=_summarize_quote),
    "orders stock place": SummarySpec(fields=ORDER_PLACE_FIELDS, summarize=_summarize_order_place),
    "orders crypto place": SummarySpec(fields=ORDER_PLACE_FIELDS, summarize=_summarize_order_place),
    "orders get": SummarySpec(fields=ORDER_DETAIL_FIELDS, summarize=_summarize_order_detail),
    "orders cancel": SummarySpec(fields=CANCEL_FIELDS, summarize=_summarize_cancel),
    "orders list": SummarySpec(fields=ORDER_DETAIL_FIELDS, summarize=_summarize_order_detail_list),
    "options chains": SummarySpec(fields=OPTIONS_CHAINS_FIELDS, summarize=_summarize_options_chains),
    "options contracts find": SummarySpec(fields=OPTION_CONTRACT_FIELDS, summarize=_summarize_option_contracts),
    "options orders place single": SummarySpec(fields=ORDER_PLACE_FIELDS, summarize=_summarize_order_place),
    "options orders place credit-spread": SummarySpec(fields=ORDER_PLACE_FIELDS, summarize=_summarize_order_place),
    "options orders place debit-spread": SummarySpec(fields=ORDER_PLACE_FIELDS, summarize=_summarize_order_place),
    "options orders get": SummarySpec(fields=ORDER_DETAIL_FIELDS, summarize=_summarize_order_detail),
    "options orders cancel": SummarySpec(fields=CANCEL_FIELDS, summarize=_summarize_cancel),
    "options orders list": SummarySpec(fields=ORDER_DETAIL_FIELDS, summarize=_summarize_order_detail_list),
    "doctor": SummarySpec(fields=DOCTOR_FIELDS, summarize=_summarize_doctor),
}


def _apply_limit(data: Any, limit: int | None) -> tuple[Any, dict[str, Any]]:
    if not isinstance(data, list):
        return data, {}

    total = len(data)
    if limit is None:
        return data, {"total_count": total, "returned_count": total, "truncated": False}

    limited = data[:limit]
    returned = len(limited)
    return limited, {"total_count": total, "returned_count": returned, "truncated": returned < total}


def shape_data(
    command: str,
    provider: str | None,
    data: dict[str, Any] | list[Any] | None,
    view: str,
    fields: list[str] | None,
    limit: int | None,
) -> tuple[dict[str, Any] | list[Any] | None, dict[str, Any]]:
    normalized_view = view.lower()
    if normalized_view not in {"summary", "full"}:
        raise CLIError(code=ErrorCode.VALIDATION_ERROR, message=f"Unsupported --view: {view}. Use summary or full.")

    spec = SUMMARY_SPECS.get(command, SummarySpec(fields=(), summarize=_summarize_identity))

    if normalized_view == "full":
        if fields:
            raise CLIError(code=ErrorCode.VALIDATION_ERROR, message="--fields requires --view summary")
        shaped_data: dict[str, Any] | list[Any] | None = data
    else:
        unknown_fields = [field for field in (fields or []) if field not in spec.fields]
        if unknown_fields:
            allowed = ", ".join(spec.fields)
            unknown = ", ".join(unknown_fields)
            raise CLIError(
                code=ErrorCode.VALIDATION_ERROR,
                message=f"Unknown field(s) for {command}: {unknown}. Allowed fields: {allowed}",
            )

        shaped_data = spec.summarize(data, provider)
        if fields:
            shaped_data = _project_fields(shaped_data, fields)

    shaped_data, count_meta = _apply_limit(shaped_data, limit)

    meta_updates: dict[str, Any] = {}
    if fields:
        meta_updates["fields"] = fields
    meta_updates.update(count_meta)
    return shaped_data, meta_updates
