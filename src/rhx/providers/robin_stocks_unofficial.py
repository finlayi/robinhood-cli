from __future__ import annotations

from typing import Any

from rhx.auth import AuthManager
from rhx.errors import CLIError, ErrorCode
from rhx.models import (
    AuthStatus,
    CapabilitySet,
    OrderIntentCrypto,
    OrderIntentOptionSingle,
    OrderIntentOptionSpread,
    OrderIntentStock,
    OrderResult,
)
from rhx.providers.base import OrderIntent


ORDER_SYMBOL_RESOLUTION_LIMIT = 200


class RobinStocksProvider:
    name = "brokerage"

    def __init__(self, auth: AuthManager) -> None:
        self.auth = auth
        self._rh = self._load_rh()

    def _load_rh(self):
        import robin_stocks.robinhood as rh

        return rh

    def _ensure_auth(self, interactive: bool = False) -> None:
        self.auth.ensure_brokerage_authenticated(interactive=interactive)

    def _call_quiet(self, fn, *args, **kwargs):
        guard = getattr(self.auth, "external_output_guard", None)
        if guard is None:
            return fn(*args, **kwargs)
        with guard():
            return fn(*args, **kwargs)

    def capabilities(self) -> CapabilitySet:
        return CapabilitySet(stocks=True, crypto=True, options=True, options_spreads=True)

    def auth_status(self) -> AuthStatus:
        return self.auth.brokerage_status()

    def account_summary(self) -> dict[str, Any]:
        self._ensure_auth(interactive=False)
        return {
            "account_profile": self._call_quiet(self._rh.load_account_profile),
            "portfolio_profile": self._call_quiet(self._rh.load_portfolio_profile),
            "user_profile": self._call_quiet(self._rh.load_user_profile),
        }

    def positions(self) -> list[dict[str, Any]]:
        self._ensure_auth(interactive=False)
        positions: list[dict[str, Any]] = []

        stock_positions = self._call_quiet(self._rh.get_open_stock_positions) or []
        for p in stock_positions:
            positions.append({"asset_type": "stock", **p})

        crypto_positions = self._call_quiet(self._rh.get_crypto_positions) or []
        for p in crypto_positions:
            positions.append({"asset_type": "crypto", **p})

        option_positions = self._call_quiet(self._rh.get_open_option_positions) or []
        for p in option_positions:
            positions.append({"asset_type": "option", **p})

        return positions

    def quote(self, symbol: str) -> dict[str, Any]:
        self._ensure_auth(interactive=False)
        if "-" in symbol:
            base = symbol.split("-", 1)[0]
            return {
                "asset_type": "crypto",
                "symbol": symbol,
                "quote": self._call_quiet(self._rh.get_crypto_quote, base),
            }

        quote = self._call_quiet(self._rh.get_quotes, symbol)
        if isinstance(quote, list):
            quote = quote[0] if quote else {}
        return {"asset_type": "stock", "symbol": symbol, "quote": quote}

    def place_order(self, intent: OrderIntent) -> OrderResult:
        self._ensure_auth(interactive=False)

        if isinstance(intent, OrderIntentStock):
            return self._place_stock_order(intent)
        if isinstance(intent, OrderIntentCrypto):
            return self._place_crypto_order(intent)
        if isinstance(intent, OrderIntentOptionSingle):
            return self._place_option_single(intent)
        if isinstance(intent, OrderIntentOptionSpread):
            return self._place_option_spread(intent)

        raise CLIError(code=ErrorCode.VALIDATION_ERROR, message="Unsupported order intent")

    def _place_stock_order(self, intent: OrderIntentStock) -> OrderResult:
        side = intent.side
        tif = intent.time_in_force

        if intent.notional_usd is not None and intent.order_type != "market":
            raise CLIError(
                code=ErrorCode.VALIDATION_ERROR,
                message="notional_usd is only supported for stock market orders",
            )

        if intent.order_type == "market":
            if intent.notional_usd is not None:
                fn = self._rh.order_buy_fractional_by_price if side == "buy" else self._rh.order_sell_fractional_by_price
                raw = self._call_quiet(
                    fn,
                    intent.symbol,
                    float(intent.notional_usd),
                    timeInForce=tif,
                    extendedHours=intent.extended_hours,
                )
            else:
                fn = self._rh.order_buy_market if side == "buy" else self._rh.order_sell_market
                raw = self._call_quiet(
                    fn,
                    intent.symbol,
                    float(intent.quantity),
                    timeInForce=tif,
                    extendedHours=intent.extended_hours,
                )

        elif intent.order_type == "limit":
            fn = self._rh.order_buy_limit if side == "buy" else self._rh.order_sell_limit
            raw = self._call_quiet(
                fn,
                intent.symbol,
                float(intent.quantity),
                float(intent.limit_price),
                timeInForce=tif,
                extendedHours=intent.extended_hours,
            )
        else:
            fn = self._rh.order_buy_stop_limit if side == "buy" else self._rh.order_sell_stop_limit
            raw = self._call_quiet(
                fn,
                intent.symbol,
                float(intent.quantity),
                float(intent.limit_price),
                float(intent.stop_price),
                timeInForce=tif,
                extendedHours=intent.extended_hours,
            )

        return self._normalize_order_result(raw, "stock", intent.symbol, intent.side)

    def _place_crypto_order(self, intent: OrderIntentCrypto) -> OrderResult:
        side = intent.side
        tif = intent.time_in_force

        if intent.order_type == "market":
            if intent.amount_in == "price":
                fn = self._rh.order_buy_crypto_by_price if side == "buy" else self._rh.order_sell_crypto_by_price
                raw = self._call_quiet(fn, intent.symbol, float(intent.notional_usd), timeInForce=tif)
            else:
                fn = self._rh.order_buy_crypto_by_quantity if side == "buy" else self._rh.order_sell_crypto_by_quantity
                raw = self._call_quiet(fn, intent.symbol, float(intent.quantity), timeInForce=tif)
        else:
            if intent.amount_in == "price":
                fn = self._rh.order_buy_crypto_limit_by_price if side == "buy" else self._rh.order_sell_crypto_limit_by_price
                raw = self._call_quiet(fn, intent.symbol, float(intent.notional_usd), float(intent.limit_price), timeInForce=tif)
            else:
                fn = self._rh.order_buy_crypto_limit if side == "buy" else self._rh.order_sell_crypto_limit
                raw = self._call_quiet(fn, intent.symbol, float(intent.quantity), float(intent.limit_price), timeInForce=tif)

        return self._normalize_order_result(raw, "crypto", intent.symbol, intent.side)

    def _place_option_single(self, intent: OrderIntentOptionSingle) -> OrderResult:
        common = dict(
            positionEffect=intent.position_effect,
            creditOrDebit=intent.credit_or_debit,
            symbol=intent.symbol,
            quantity=intent.quantity,
            expirationDate=intent.expiration_date,
            strike=float(intent.strike),
            optionType=intent.option_type,
            timeInForce=intent.time_in_force,
        )

        if intent.side == "buy" and intent.order_type == "limit":
            raw = self._call_quiet(self._rh.order_buy_option_limit, price=float(intent.price), **common)
        elif intent.side == "buy" and intent.order_type == "stop_limit":
            raw = self._call_quiet(
                self._rh.order_buy_option_stop_limit,
                limitPrice=float(intent.limit_price),
                stopPrice=float(intent.stop_price),
                **common,
            )
        elif intent.side == "sell" and intent.order_type == "limit":
            raw = self._call_quiet(self._rh.order_sell_option_limit, price=float(intent.price), **common)
        else:
            raw = self._call_quiet(
                self._rh.order_sell_option_stop_limit,
                limitPrice=float(intent.limit_price),
                stopPrice=float(intent.stop_price),
                **common,
            )

        return self._normalize_order_result(raw, "option_single", intent.symbol, intent.side)

    def _place_option_spread(self, intent: OrderIntentOptionSpread) -> OrderResult:
        spread = [leg.model_dump(mode="python") for leg in intent.spread]
        if intent.direction == "credit":
            raw = self._call_quiet(
                self._rh.order_option_credit_spread,
                price=float(intent.price),
                symbol=intent.symbol,
                quantity=int(intent.quantity),
                spread=spread,
                timeInForce=intent.time_in_force,
            )
        else:
            raw = self._call_quiet(
                self._rh.order_option_debit_spread,
                price=float(intent.price),
                symbol=intent.symbol,
                quantity=int(intent.quantity),
                spread=spread,
                timeInForce=intent.time_in_force,
            )

        return self._normalize_order_result(raw, "option_spread", intent.symbol, intent.direction)

    def _normalize_order_result(self, raw: Any, asset_type: str, symbol: str | None, side: str | None) -> OrderResult:
        payload = raw if isinstance(raw, dict) else {"response": raw}

        order_id = payload.get("id") or payload.get("order_id")
        state = payload.get("state") or payload.get("status") or payload.get("detail")

        return OrderResult(
            provider=self.name,
            order_id=order_id,
            state=str(state) if state is not None else None,
            symbol=symbol,
            side=side,
            asset_type=asset_type,
            raw=payload,
        )

    def cancel_order(self, order_id: str, asset_type: str | None = None) -> dict[str, Any]:
        self._ensure_auth(interactive=False)

        funcs = self._cancel_funcs(asset_type)
        errors: list[str] = []

        for kind, fn in funcs:
            try:
                result = self._call_quiet(fn, order_id)
                return {"asset_type": kind, "result": result}
            except Exception as exc:
                errors.append(f"{kind}: {exc}")

        raise CLIError(code=ErrorCode.BROKER_REJECTED, message="Unable to cancel order: " + "; ".join(errors))

    def get_order(self, order_id: str, asset_type: str | None = None) -> dict[str, Any]:
        self._ensure_auth(interactive=False)

        funcs = self._get_order_funcs(asset_type)
        errors: list[str] = []
        for kind, fn in funcs:
            try:
                result = self._call_quiet(fn, order_id)
                if result:
                    return {"asset_type": kind, "order": result}
            except Exception as exc:
                errors.append(f"{kind}: {exc}")

        raise CLIError(code=ErrorCode.BROKER_REJECTED, message="Unable to retrieve order: " + "; ".join(errors))

    def list_orders(
        self,
        open_only: bool = False,
        asset_type: str | None = None,
        symbol_resolve_limit: int | None = None,
    ) -> list[dict[str, Any]]:
        self._ensure_auth(interactive=False)

        items: list[dict[str, Any]] = []
        if asset_type in (None, "stock"):
            stock = (
                self._call_quiet(self._rh.get_all_open_stock_orders)
                if open_only
                else self._call_quiet(self._rh.get_all_stock_orders)
            )
            for row in stock or []:
                items.append({"asset_type": "stock", **row})

        if asset_type in (None, "option"):
            options = (
                self._call_quiet(self._rh.get_all_open_option_orders)
                if open_only
                else self._call_quiet(self._rh.get_all_option_orders)
            )
            for row in options or []:
                items.append({"asset_type": "option", **row})

        if asset_type in (None, "crypto"):
            crypto = (
                self._call_quiet(self._rh.get_all_open_crypto_orders)
                if open_only
                else self._call_quiet(self._rh.get_all_crypto_orders)
            )
            for row in crypto or []:
                items.append({"asset_type": "crypto", **row})

        self._hydrate_stock_order_symbols(items, symbol_resolve_limit)
        return items

    def option_chains(self, symbol: str) -> dict[str, Any]:
        self._ensure_auth(interactive=False)
        return self._call_quiet(self._rh.get_chains, symbol)

    def option_contracts_find(
        self,
        symbol: str,
        expiration_date: str | None = None,
        strike_price: float | None = None,
        option_type: str | None = None,
    ) -> list[dict[str, Any]]:
        self._ensure_auth(interactive=False)

        if expiration_date and strike_price is not None:
            result = self._call_quiet(
                self._rh.find_options_by_expiration_and_strike,
                symbol,
                expiration_date,
                strike_price,
                optionType=option_type,
            )
        elif expiration_date:
            result = self._call_quiet(self._rh.find_options_by_expiration, symbol, expiration_date, optionType=option_type)
        elif strike_price is not None:
            result = self._call_quiet(self._rh.find_options_by_strike, symbol, strike_price, optionType=option_type)
        else:
            result = self._call_quiet(self._rh.find_tradable_options, symbol, optionType=option_type)

        return result or []

    def _hydrate_stock_order_symbols(self, items: list[dict[str, Any]], symbol_resolve_limit: int | None) -> None:
        if not items:
            return

        row_limit = ORDER_SYMBOL_RESOLUTION_LIMIT
        if symbol_resolve_limit is not None:
            row_limit = min(max(symbol_resolve_limit, 0), ORDER_SYMBOL_RESOLUTION_LIMIT)
        if row_limit <= 0:
            return

        cache: dict[str, str | None] = {}
        for row in items[:row_limit]:
            if row.get("asset_type") != "stock":
                continue

            symbol = row.get("symbol")
            if isinstance(symbol, str) and symbol.strip():
                continue

            instrument = row.get("instrument")
            if not isinstance(instrument, str) or not instrument:
                continue

            if instrument not in cache:
                try:
                    resolved = self._call_quiet(self._rh.get_symbol_by_url, instrument)
                except Exception:
                    resolved = None
                cache[instrument] = resolved if isinstance(resolved, str) and resolved else None

            resolved_symbol = cache[instrument]
            if resolved_symbol:
                row["symbol"] = resolved_symbol

    def _cancel_funcs(self, asset_type: str | None):
        if asset_type == "stock":
            return [("stock", self._rh.cancel_stock_order)]
        if asset_type == "option":
            return [("option", self._rh.cancel_option_order)]
        if asset_type == "crypto":
            return [("crypto", self._rh.cancel_crypto_order)]
        return [
            ("stock", self._rh.cancel_stock_order),
            ("option", self._rh.cancel_option_order),
            ("crypto", self._rh.cancel_crypto_order),
        ]

    def _get_order_funcs(self, asset_type: str | None):
        if asset_type == "stock":
            return [("stock", self._rh.get_stock_order_info)]
        if asset_type == "option":
            return [("option", self._rh.get_option_order_info)]
        if asset_type == "crypto":
            return [("crypto", self._rh.get_crypto_order_info)]
        return [
            ("stock", self._rh.get_stock_order_info),
            ("option", self._rh.get_option_order_info),
            ("crypto", self._rh.get_crypto_order_info),
        ]
