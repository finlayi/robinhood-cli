from __future__ import annotations

from typing import Any

from rhx.auth import AuthManager
from rhx.errors import CLIError, ErrorCode
from rhx.models import (
    AuthStatus,
    CapabilitySet,
    OptionQuoteRecord,
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

    def quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        self._ensure_auth(interactive=False)
        requested = [symbol.strip() for symbol in symbols if symbol and symbol.strip()]
        if not requested:
            return []

        stock_symbols = [symbol for symbol in requested if "-" not in symbol]
        crypto_symbols = [symbol for symbol in requested if "-" in symbol]

        stock_rows: dict[str, dict[str, Any]] = {}
        if stock_symbols:
            raw = self._call_quiet(self._rh.get_quotes, stock_symbols)
            quote_rows = raw if isinstance(raw, list) else ([raw] if isinstance(raw, dict) else [])
            for idx, row in enumerate(quote_rows):
                if not isinstance(row, dict):
                    continue
                symbol = row.get("symbol")
                if not isinstance(symbol, str) or not symbol:
                    if idx < len(stock_symbols):
                        symbol = stock_symbols[idx]
                    else:
                        continue
                stock_rows[symbol.upper()] = {"asset_type": "stock", "symbol": symbol, "quote": row}

        crypto_rows: dict[str, dict[str, Any]] = {}
        for symbol in crypto_symbols:
            base = symbol.split("-", 1)[0]
            quote = self._call_quiet(self._rh.get_crypto_quote, base)
            crypto_rows[symbol.upper()] = {"asset_type": "crypto", "symbol": symbol, "quote": quote}

        rows: list[dict[str, Any]] = []
        for symbol in requested:
            normalized = symbol.upper()
            if normalized in stock_rows:
                rows.append(stock_rows[normalized])
                continue
            if normalized in crypto_rows:
                rows.append(crypto_rows[normalized])
        return rows

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

    def option_expirations(self, symbol: str) -> list[str]:
        chain = self.option_chains(symbol)
        expirations = chain.get("expiration_dates")
        if not isinstance(expirations, list):
            return []
        return sorted({str(value) for value in expirations if isinstance(value, str) and value})

    def option_strikes(
        self,
        symbol: str,
        expiration_date: str,
        option_type: str | None = None,
    ) -> list[float]:
        contracts = self.option_contracts_find(
            symbol=symbol,
            expiration_date=expiration_date,
            option_type=self._normalize_option_type(option_type),
        )
        strikes: set[float] = set()
        for contract in contracts:
            strike = self._safe_float(contract.get("strike_price"))
            if strike is not None:
                strikes.add(strike)
        return sorted(strikes)

    def option_quote_get(
        self,
        symbol: str,
        expiration_date: str,
        strike_price: float,
        option_type: str,
    ) -> dict[str, Any]:
        self._ensure_auth(interactive=False)
        normalized_type = self._normalize_option_type(option_type, allow_both=False)

        instrument = self._call_quiet(
            self._rh.get_option_instrument_data,
            symbol,
            expiration_date,
            strike_price,
            normalized_type,
        )
        if isinstance(instrument, list):
            instrument = instrument[0] if instrument else {}
        if not isinstance(instrument, dict):
            instrument = {}

        market = self._call_quiet(
            self._rh.get_option_market_data,
            symbol,
            expiration_date,
            strike_price,
            normalized_type,
        )
        if isinstance(market, list):
            market = market[0] if market else {}
        if not isinstance(market, dict):
            market = {}

        quote = self._normalize_option_quote(
            symbol=symbol,
            expiration_date=expiration_date,
            strike_price=strike_price,
            option_type=normalized_type,
            contract=instrument,
            market=market,
        )
        return quote.model_dump(mode="python")

    def option_quotes_list(
        self,
        symbol: str,
        expiration_date: str,
        option_type: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_type = self._normalize_option_type(option_type)
        contracts = self.option_contracts_find(
            symbol=symbol,
            expiration_date=expiration_date,
            option_type=normalized_type,
        )

        rows: list[dict[str, Any]] = []
        for contract in contracts:
            if not isinstance(contract, dict):
                continue
            market = self._option_market_data_for_contract(contract)
            strike_value = self._safe_float(contract.get("strike_price"))
            if strike_value is None:
                continue
            quote = self._normalize_option_quote(
                symbol=symbol,
                expiration_date=expiration_date,
                strike_price=strike_value,
                option_type=str(contract.get("type") or normalized_type or "").lower() or "call",
                contract=contract,
                market=market,
            )
            rows.append(quote.model_dump(mode="python"))
        return rows

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

    def _normalize_option_type(self, option_type: str | None, allow_both: bool = True) -> str | None:
        if option_type is None:
            return None
        normalized = option_type.strip().lower()
        if allow_both and normalized in {"", "both"}:
            return None
        if normalized not in {"call", "put"}:
            raise CLIError(code=ErrorCode.VALIDATION_ERROR, message=f"Unsupported option type: {option_type}")
        return normalized

    def _safe_float(self, value: Any) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _safe_str(self, value: Any) -> str | None:
        if value is None:
            return None
        return str(value)

    def _option_market_data_for_contract(self, contract: dict[str, Any]) -> dict[str, Any]:
        market: Any = {}
        market_by_id_available = False
        contract_id = contract.get("id")
        if isinstance(contract_id, str) and contract_id:
            try:
                market = self._call_quiet(self._rh.get_option_market_data_by_id, contract_id)
                market_by_id_available = True
            except Exception:
                market = {}

        if market_by_id_available:
            if isinstance(market, list):
                market = market[0] if market else {}
            if isinstance(market, dict):
                return market
            return {}

        chain_symbol = contract.get("chain_symbol")
        expiration_date = contract.get("expiration_date")
        strike_price = contract.get("strike_price")
        option_type = contract.get("type")
        if not all((chain_symbol, expiration_date, strike_price, option_type)):
            return {}

        try:
            market = self._call_quiet(
                self._rh.get_option_market_data,
                chain_symbol,
                expiration_date,
                float(strike_price),
                option_type,
            )
        except Exception:
            return {}

        if isinstance(market, list):
            market = market[0] if market else {}
        return market if isinstance(market, dict) else {}

    def _normalize_option_quote(
        self,
        *,
        symbol: str,
        expiration_date: str,
        strike_price: float,
        option_type: str,
        contract: dict[str, Any] | None = None,
        market: dict[str, Any] | None = None,
    ) -> OptionQuoteRecord:
        contract_payload = contract or {}
        market_payload = market or {}
        greeks = market_payload.get("greeks")
        greeks_payload = greeks if isinstance(greeks, dict) else {}

        resolved_type = str(contract_payload.get("type") or option_type or "call").lower()
        if resolved_type not in {"call", "put"}:
            resolved_type = "call"

        return OptionQuoteRecord(
            contract_id=self._safe_str(contract_payload.get("id")),
            symbol=self._safe_str(contract_payload.get("chain_symbol")) or symbol,
            expiration_date=self._safe_str(contract_payload.get("expiration_date")) or expiration_date,
            strike_price=self._safe_float(contract_payload.get("strike_price")) or strike_price,
            option_type=resolved_type,
            bid_price=self._safe_str(market_payload.get("bid_price") or market_payload.get("bid")),
            ask_price=self._safe_str(market_payload.get("ask_price") or market_payload.get("ask")),
            mark_price=self._safe_str(
                market_payload.get("mark_price")
                or market_payload.get("adjusted_mark_price")
                or market_payload.get("mark")
            ),
            last_trade_price=self._safe_str(
                market_payload.get("last_trade_price")
                or market_payload.get("last_trade_price_24h")
            ),
            implied_volatility=self._safe_str(market_payload.get("implied_volatility") or market_payload.get("iv")),
            delta=self._safe_str(market_payload.get("delta") or greeks_payload.get("delta")),
            gamma=self._safe_str(market_payload.get("gamma") or greeks_payload.get("gamma")),
            theta=self._safe_str(market_payload.get("theta") or greeks_payload.get("theta")),
            vega=self._safe_str(market_payload.get("vega") or greeks_payload.get("vega")),
            rho=self._safe_str(market_payload.get("rho") or greeks_payload.get("rho")),
            open_interest=self._safe_str(market_payload.get("open_interest")),
            volume=self._safe_str(market_payload.get("volume")),
            updated_at=self._safe_str(market_payload.get("updated_at") or contract_payload.get("updated_at")),
            tradability=self._safe_str(contract_payload.get("tradability")),
            state=self._safe_str(contract_payload.get("state")),
        )
