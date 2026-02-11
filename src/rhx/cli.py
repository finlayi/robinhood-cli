from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import typer
from click.core import ParameterSource
from pydantic import BaseModel, ValidationError

from rhx.auth import AuthManager
from rhx.config import (
    RuntimeConfig,
    default_config_path,
    load_runtime_config,
    save_runtime_config,
)
from rhx.errors import CLIError, ErrorCode
from rhx.models import (
    OrderIntentCrypto,
    OrderIntentOptionSingle,
    OrderIntentOptionSpread,
    OrderIntentStock,
    OptionLeg,
)
from rhx.output import emit_error, emit_success, map_unexpected_error
from rhx.output_shape import shape_data
from rhx.providers.crypto_official import RobinhoodCryptoProvider
from rhx.providers.robin_stocks_unofficial import RobinStocksProvider
from rhx.safety import SafetyEngine


app = typer.Typer(no_args_is_help=True, help="Auth-first Robinhood CLI wrapper")
auth_app = typer.Typer(no_args_is_help=True)
live_app = typer.Typer(no_args_is_help=True)
account_app = typer.Typer(no_args_is_help=True)
positions_app = typer.Typer(no_args_is_help=True)
quote_app = typer.Typer(no_args_is_help=True)
orders_app = typer.Typer(no_args_is_help=True)
orders_stock_app = typer.Typer(no_args_is_help=True)
orders_crypto_app = typer.Typer(no_args_is_help=True)
options_app = typer.Typer(no_args_is_help=True)
options_contracts_app = typer.Typer(no_args_is_help=True)
options_orders_app = typer.Typer(no_args_is_help=True)
options_orders_place_app = typer.Typer(no_args_is_help=True)
options_quotes_app = typer.Typer(no_args_is_help=True)
portfolio_app = typer.Typer(no_args_is_help=True)

app.add_typer(auth_app, name="auth")
app.add_typer(live_app, name="live")
app.add_typer(account_app, name="account")
app.add_typer(positions_app, name="positions")
app.add_typer(quote_app, name="quote")
app.add_typer(orders_app, name="orders")
orders_app.add_typer(orders_stock_app, name="stock")
orders_app.add_typer(orders_crypto_app, name="crypto")
app.add_typer(options_app, name="options")
options_app.add_typer(options_contracts_app, name="contracts")
options_app.add_typer(options_orders_app, name="orders")
options_orders_app.add_typer(options_orders_place_app, name="place")
options_app.add_typer(options_quotes_app, name="quotes")
app.add_typer(portfolio_app, name="portfolio")


@dataclass
class AppRuntime:
    json_mode: bool
    human_mode: bool
    view: str
    fields: list[str] | None
    limit: int | None
    provider_choice: str
    config: RuntimeConfig
    auth: AuthManager
    safety: SafetyEngine
    brokerage_provider: RobinStocksProvider
    crypto_provider: RobinhoodCryptoProvider


@dataclass
class CommandOutput:
    data: Any
    meta_updates: dict[str, Any] | None = None


def _serialize(data: Any) -> Any:
    if isinstance(data, BaseModel):
        return data.model_dump(mode="python")
    if isinstance(data, list):
        return [_serialize(item) for item in data]
    if isinstance(data, dict):
        return {k: _serialize(v) for k, v in data.items()}
    return data


def _runtime(ctx: typer.Context) -> AppRuntime:
    runtime = ctx.obj
    if runtime is None:
        raise RuntimeError("CLI runtime not initialized")
    return runtime


def _json_meta(runtime: AppRuntime) -> dict[str, Any] | None:
    if not runtime.json_mode:
        return None
    return {"output_schema": "v3", "view": runtime.view}


def _parse_fields(fields: str | None) -> list[str] | None:
    if fields is None:
        return None

    parsed: list[str] = []
    for raw in fields.split(","):
        field = raw.strip()
        if not field:
            continue
        if field not in parsed:
            parsed.append(field)

    if not parsed:
        raise CLIError(code=ErrorCode.VALIDATION_ERROR, message="--fields requires at least one field name")
    return parsed


def _parse_symbols(symbols: str) -> list[str]:
    parsed: list[str] = []
    for raw in symbols.split(","):
        symbol = raw.strip()
        if not symbol:
            continue
        if symbol not in parsed:
            parsed.append(symbol)
    if not parsed:
        raise CLIError(code=ErrorCode.VALIDATION_ERROR, message="--symbols requires at least one symbol")
    return parsed


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_iso_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _parse_yyyy_mm_dd(value: str, *, arg_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CLIError(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"{arg_name} must be in YYYY-MM-DD format",
        ) from exc


def _query_meta(*, total_count: int, returned_count: int, offset: int = 0) -> dict[str, Any]:
    return {
        "query_total_count": total_count,
        "query_returned_count": returned_count,
        "query_truncated": returned_count < total_count,
        "query_offset": offset,
    }


def _flatten_quote_payload(row: dict[str, Any], *, provider: str) -> dict[str, Any]:
    quote = row.get("quote")
    quote_payload = quote if isinstance(quote, dict) else {}
    return {
        "symbol": row.get("symbol"),
        "asset_type": row.get("asset_type"),
        "provider": provider,
        "bid_price": quote_payload.get("bid_price") or quote_payload.get("bid"),
        "ask_price": quote_payload.get("ask_price") or quote_payload.get("ask"),
        "mark_price": quote_payload.get("mark_price") or quote_payload.get("mark"),
        "last_trade_price": quote_payload.get("last_trade_price") or quote_payload.get("price"),
        "updated_at": quote_payload.get("updated_at"),
        "error": row.get("error"),
    }


def _is_from_cli(ctx: typer.Context, parameter_name: str) -> bool:
    source = ctx.get_parameter_source(parameter_name)
    return source == ParameterSource.COMMANDLINE


def _is_crypto_symbol(symbol: str) -> bool:
    normalized = symbol.upper()
    return "-" in normalized or normalized.endswith("USD")


def _resolve_provider(runtime: AppRuntime, symbol: str | None = None, force: str | None = None):
    choice = (force or runtime.provider_choice or "auto").lower()

    if choice == "brokerage":
        return runtime.brokerage_provider
    if choice == "crypto":
        return runtime.crypto_provider

    if symbol and _is_crypto_symbol(symbol):
        crypto_status = runtime.auth.crypto_status()
        if crypto_status.authenticated:
            return runtime.crypto_provider
    return runtime.brokerage_provider


def _run_command(
    ctx: typer.Context,
    command: str,
    func,
    *,
    provider: str | None = None,
) -> None:
    runtime = _runtime(ctx)
    try:
        raw_result = func()
        extra_meta: dict[str, Any] | None = None
        if isinstance(raw_result, CommandOutput):
            payload = _serialize(raw_result.data)
            extra_meta = raw_result.meta_updates
        else:
            payload = _serialize(raw_result)

        meta_updates: dict[str, Any] | None = extra_meta
        if runtime.json_mode:
            payload, shape_meta = shape_data(
                command=command,
                provider=provider,
                data=payload,
                view=runtime.view,
                fields=runtime.fields,
                limit=runtime.limit,
            )
            combined_meta: dict[str, Any] = {}
            if extra_meta:
                combined_meta.update(extra_meta)
            combined_meta.update(shape_meta)
            meta_updates = combined_meta
        emit_success(
            command,
            payload,
            runtime.json_mode,
            provider,
            meta_updates=meta_updates,
            view=runtime.view,
            human_mode=runtime.human_mode,
        )
    except CLIError as err:
        emit_error(err, command, runtime.json_mode, provider, meta_updates=_json_meta(runtime), view=runtime.view)
        raise typer.Exit(err.exit_code)
    except ValidationError as err:
        cli_err = CLIError(code=ErrorCode.VALIDATION_ERROR, message=str(err))
        emit_error(cli_err, command, runtime.json_mode, provider, meta_updates=_json_meta(runtime), view=runtime.view)
        raise typer.Exit(cli_err.exit_code)
    except Exception as exc:  # pragma: no cover
        cli_err = map_unexpected_error(exc)
        emit_error(cli_err, command, runtime.json_mode, provider, meta_updates=_json_meta(runtime), view=runtime.view)
        raise typer.Exit(cli_err.exit_code)


@app.callback()
def main(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output"),
    human_output: bool = typer.Option(False, "--human", help="Emit compact human-readable output"),
    view: str = typer.Option("summary", "--view", help="JSON view: summary|full"),
    fields: str | None = typer.Option(None, "--fields", help="Comma-separated top-level fields for summary view"),
    limit: int | None = typer.Option(None, "--limit", help="Limit list rows in JSON output"),
    profile: str = typer.Option("default", "--profile", help="Credential/profile namespace"),
    provider: str = typer.Option("auto", "--provider", help="Provider preference: auto|crypto|brokerage"),
    config: Path = typer.Option(default_config_path(), "--config", help="Config path"),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose logs"),
    no_color: bool = typer.Option(False, "--no-color", help="Disable color output"),
) -> None:
    del no_color

    view_normalized = view.lower().strip()
    parsed_fields = _parse_fields(fields)

    if view_normalized not in {"summary", "full"}:
        err = CLIError(code=ErrorCode.VALIDATION_ERROR, message=f"Unsupported --view: {view}. Use summary or full.")
        emit_error(
            err,
            "global options",
            json_output,
            provider=None,
            meta_updates={"output_schema": "v3", "view": view_normalized or "summary"},
            view=view_normalized or "summary",
        )
        raise typer.Exit(err.exit_code)

    if json_output and human_output:
        err = CLIError(code=ErrorCode.VALIDATION_ERROR, message="--human cannot be used with --json")
        emit_error(
            err,
            "global options",
            json_output,
            provider=None,
            meta_updates={"output_schema": "v3", "view": view_normalized},
            view=view_normalized,
        )
        raise typer.Exit(err.exit_code)

    if limit is not None and limit < 1:
        err = CLIError(code=ErrorCode.VALIDATION_ERROR, message="--limit must be >= 1")
        emit_error(
            err,
            "global options",
            json_output,
            provider=None,
            meta_updates={"output_schema": "v3", "view": view_normalized},
            view=view_normalized,
        )
        raise typer.Exit(err.exit_code)

    controls_used = parsed_fields is not None or limit is not None or _is_from_cli(ctx, "view")
    if not json_output and controls_used:
        err = CLIError(code=ErrorCode.VALIDATION_ERROR, message="--view, --fields, and --limit require --json")
        emit_error(err, "global options", json_output, provider=None, view=view_normalized)
        raise typer.Exit(err.exit_code)

    if parsed_fields is not None and view_normalized != "summary":
        err = CLIError(code=ErrorCode.VALIDATION_ERROR, message="--fields requires --view summary")
        emit_error(
            err,
            "global options",
            json_output,
            provider=None,
            meta_updates={"output_schema": "v3", "view": view_normalized},
            view=view_normalized,
        )
        raise typer.Exit(err.exit_code)

    runtime_cfg = load_runtime_config(config_path=config, profile=profile)
    auth = AuthManager(
        profile=profile,
        session_dir=runtime_cfg.paths.session_dir,
        suppress_external_output=json_output,
        verbose=verbose,
    )
    safety = SafetyEngine(db_path=runtime_cfg.paths.state_db_path, config=runtime_cfg.app.safety)

    runtime = AppRuntime(
        json_mode=json_output,
        human_mode=human_output,
        view=view_normalized,
        fields=parsed_fields,
        limit=limit,
        provider_choice=provider,
        config=runtime_cfg,
        auth=auth,
        safety=safety,
        brokerage_provider=RobinStocksProvider(auth=auth),
        crypto_provider=RobinhoodCryptoProvider(auth=auth),
    )
    ctx.obj = runtime


@auth_app.command("login")
def auth_login(
    ctx: typer.Context,
    non_interactive: bool = typer.Option(False, "--non-interactive", help="Fail instead of prompting for credentials"),
    force: bool = typer.Option(False, "--force", help="Force login even if cached session exists"),
) -> None:
    runtime = _runtime(ctx)

    def _do():
        status = runtime.auth.ensure_brokerage_authenticated(interactive=not non_interactive, force=force)
        return {
            "brokerage": status.model_dump(mode="python"),
            "session_pickle": str(runtime.auth.session_pickle_path),
        }

    _run_command(ctx, "auth login", _do, provider="brokerage")


@auth_app.command("status")
def auth_status(ctx: typer.Context) -> None:
    runtime = _runtime(ctx)

    def _do():
        brokerage = runtime.auth.brokerage_passive_status()
        crypto = runtime.auth.crypto_status()
        return {
            "brokerage": brokerage.model_dump(mode="python"),
            "crypto": crypto.model_dump(mode="python"),
        }

    _run_command(ctx, "auth status", _do)


@auth_app.command("verify")
def auth_verify(ctx: typer.Context) -> None:
    runtime = _runtime(ctx)

    def _do():
        brokerage = runtime.auth.brokerage_status()
        crypto = runtime.crypto_provider.auth_status()
        return {
            "brokerage": brokerage.model_dump(mode="python"),
            "crypto": crypto.model_dump(mode="python"),
        }

    _run_command(ctx, "auth verify", _do)


@auth_app.command("refresh")
def auth_refresh(
    ctx: typer.Context,
    non_interactive: bool = typer.Option(False, "--non-interactive", help="Fail instead of prompting MFA/credentials"),
) -> None:
    runtime = _runtime(ctx)

    def _do():
        status = runtime.auth.refresh_brokerage(interactive=not non_interactive)
        return {"brokerage": status.model_dump(mode="python")}

    _run_command(ctx, "auth refresh", _do, provider="brokerage")


@auth_app.command("logout")
def auth_logout(
    ctx: typer.Context,
    forget_creds: bool = typer.Option(False, "--forget-creds", help="Also delete stored keychain credentials"),
) -> None:
    runtime = _runtime(ctx)

    def _do():
        runtime.auth.logout_brokerage(forget_creds=forget_creds)
        if forget_creds:
            runtime.auth.store.delete_crypto_credentials(runtime.auth.profile)
        return {
            "logged_out": True,
            "forget_creds": forget_creds,
            "session_pickle": str(runtime.auth.session_pickle_path),
        }

    _run_command(ctx, "auth logout", _do)


@live_app.command("on")
def live_on(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation prompt"),
    ttl_seconds: int | None = typer.Option(
        None,
        "--ttl-seconds",
        help="Live token TTL in seconds (defaults to config safety.live_unlock_ttl_seconds)",
    ),
) -> None:
    runtime = _runtime(ctx)

    def _do():
        if not yes:
            confirm = typer.confirm("Enable live mode? This allows order placement.")
            if not confirm:
                raise CLIError(code=ErrorCode.VALIDATION_ERROR, message="Live mode not enabled")

        runtime.config.app.safety.live_mode = True
        runtime.safety.set_live_mode(True)
        if ttl_seconds is not None:
            runtime.config.app.safety.live_unlock_ttl_seconds = max(1, int(ttl_seconds))
        token, expires_at = runtime.safety.issue_live_unlock(runtime.config.app.safety.live_unlock_ttl_seconds)
        save_runtime_config(runtime.config)
        return {
            "live_mode": True,
            "live_confirm_token": token,
            "expires_at": expires_at,
            "ttl_seconds": runtime.config.app.safety.live_unlock_ttl_seconds,
        }

    _run_command(ctx, "live on", _do)


@live_app.command("off")
def live_off(ctx: typer.Context) -> None:
    runtime = _runtime(ctx)

    def _do():
        runtime.config.app.safety.live_mode = False
        runtime.safety.set_live_mode(False)
        runtime.safety.clear_live_unlock()
        save_runtime_config(runtime.config)
        return {"live_mode": False}

    _run_command(ctx, "live off", _do)


@live_app.command("status")
def live_status(ctx: typer.Context) -> None:
    runtime = _runtime(ctx)

    def _do():
        return {
            "live_mode": runtime.safety.live_mode_enabled(),
            "live_unlock": runtime.safety.live_unlock_status(),
        }

    _run_command(ctx, "live status", _do)


@account_app.command("summary")
def account_summary(ctx: typer.Context) -> None:
    runtime = _runtime(ctx)

    def _do():
        provider = _resolve_provider(runtime)
        return provider.account_summary()

    provider = _resolve_provider(runtime)
    _run_command(ctx, "account summary", _do, provider=provider.name)


@positions_app.command("list")
def positions_list(ctx: typer.Context) -> None:
    runtime = _runtime(ctx)

    def _do():
        provider = _resolve_provider(runtime)
        return provider.positions()

    provider = _resolve_provider(runtime)
    _run_command(ctx, "positions list", _do, provider=provider.name)


@quote_app.command("get")
def quote_get(ctx: typer.Context, symbol: str = typer.Argument(...)) -> None:
    runtime = _runtime(ctx)

    provider = _resolve_provider(runtime, symbol=symbol)

    def _do():
        return provider.quote(symbol)

    _run_command(ctx, "quote get", _do, provider=provider.name)


@quote_app.command("list")
def quote_list(
    ctx: typer.Context,
    symbols: str = typer.Option(..., "--symbols", help="Comma-separated symbol list"),
    strict: bool = typer.Option(False, "--strict", help="Fail command when any symbol quote fails"),
) -> None:
    runtime = _runtime(ctx)
    requested = _parse_symbols(symbols)

    def _do():
        by_provider: dict[str, list[str]] = {}
        provider_lookup: dict[str, Any] = {}

        if runtime.provider_choice == "auto":
            for symbol in requested:
                provider = _resolve_provider(runtime, symbol=symbol)
                provider_lookup[symbol] = provider
                by_provider.setdefault(provider.name, []).append(symbol)
        else:
            provider = _resolve_provider(runtime)
            for symbol in requested:
                provider_lookup[symbol] = provider
            by_provider[provider.name] = requested[:]

        rows_by_symbol: dict[str, dict[str, Any]] = {}
        errors: list[str] = []

        for provider_name, provider_symbols in by_provider.items():
            provider = provider_lookup[provider_symbols[0]]
            try:
                provider_rows = provider.quotes(provider_symbols)
            except Exception as exc:
                if strict:
                    raise
                for symbol in provider_symbols:
                    rows_by_symbol[symbol] = {
                        "symbol": symbol,
                        "asset_type": "crypto" if _is_crypto_symbol(symbol) else "stock",
                        "provider": provider_name,
                        "bid_price": None,
                        "ask_price": None,
                        "mark_price": None,
                        "last_trade_price": None,
                        "updated_at": None,
                        "error": str(exc),
                    }
                    errors.append(symbol)
                continue

            provider_rows = provider_rows if isinstance(provider_rows, list) else []
            normalized_rows: dict[str, dict[str, Any]] = {}
            for row in provider_rows:
                if not isinstance(row, dict):
                    continue
                symbol = row.get("symbol")
                if isinstance(symbol, str) and symbol:
                    normalized_rows[symbol.upper()] = _flatten_quote_payload(row, provider=provider_name)

            for symbol in provider_symbols:
                flattened = normalized_rows.get(symbol.upper())
                if flattened is None:
                    message = f"No quote returned for {symbol}"
                    if strict:
                        raise CLIError(code=ErrorCode.BROKER_REJECTED, message=message)
                    flattened = {
                        "symbol": symbol,
                        "asset_type": "crypto" if _is_crypto_symbol(symbol) else "stock",
                        "provider": provider_name,
                        "bid_price": None,
                        "ask_price": None,
                        "mark_price": None,
                        "last_trade_price": None,
                        "updated_at": None,
                        "error": message,
                    }
                    errors.append(symbol)
                rows_by_symbol[symbol] = flattened

        if strict and errors:
            raise CLIError(
                code=ErrorCode.BROKER_REJECTED,
                message=f"Quote retrieval failed for symbols: {', '.join(errors)}",
            )

        ordered_rows = [rows_by_symbol[symbol] for symbol in requested if symbol in rows_by_symbol]
        return ordered_rows

    _run_command(ctx, "quote list", _do, provider=runtime.provider_choice)


@portfolio_app.command("analyze")
def portfolio_analyze(
    ctx: typer.Context,
    top: int = typer.Option(10, "--top"),
    include_holdings: bool = typer.Option(True, "--include-holdings/--no-include-holdings"),
) -> None:
    runtime = _runtime(ctx)

    def _do():
        if top < 1:
            raise CLIError(code=ErrorCode.VALIDATION_ERROR, message="--top must be >= 1")

        summary = runtime.brokerage_provider.account_summary()
        positions = runtime.brokerage_provider.positions()

        quote_symbols: list[str] = []
        symbol_to_quote_symbol: dict[str, str] = {}

        for row in positions:
            if not isinstance(row, dict):
                continue
            asset_type = str(row.get("asset_type") or "").lower()
            if asset_type not in {"stock", "crypto"}:
                continue
            symbol = row.get("symbol")
            if not symbol and isinstance(row.get("currency"), dict):
                symbol = row["currency"].get("code") or row["currency"].get("display_code")
            if not isinstance(symbol, str) or not symbol:
                continue
            quote_symbol = symbol if asset_type == "stock" or "-" in symbol else f"{symbol}-USD"
            symbol_to_quote_symbol[symbol] = quote_symbol
            if quote_symbol not in quote_symbols:
                quote_symbols.append(quote_symbol)

        quote_rows = runtime.brokerage_provider.quotes(quote_symbols)
        quote_by_symbol: dict[str, dict[str, Any]] = {}
        for row in quote_rows:
            if not isinstance(row, dict):
                continue
            symbol = row.get("symbol")
            if isinstance(symbol, str) and symbol:
                quote_by_symbol[symbol.upper()] = row

        account_profile = summary.get("account_profile", {}) if isinstance(summary, dict) else {}
        portfolio_profile = summary.get("portfolio_profile", {}) if isinstance(summary, dict) else {}
        margin_balances = account_profile.get("margin_balances", {}) if isinstance(account_profile, dict) else {}

        equity = _safe_float(portfolio_profile.get("equity"))
        market_value = _safe_float(portfolio_profile.get("market_value"))
        cash = _safe_float(account_profile.get("cash"))
        buying_power = _safe_float(account_profile.get("buying_power"))
        withdrawable = _safe_float(
            portfolio_profile.get("withdrawable_amount") or account_profile.get("cash_available_for_withdrawal")
        )
        margin_debit = _safe_float(margin_balances.get("settled_amount_borrowed"))

        holdings_all: list[dict[str, Any]] = []
        for row in positions:
            if not isinstance(row, dict):
                continue
            asset_type = str(row.get("asset_type") or "").lower()
            if asset_type not in {"stock", "crypto"}:
                continue

            symbol = row.get("symbol")
            if not symbol and isinstance(row.get("currency"), dict):
                symbol = row["currency"].get("code") or row["currency"].get("display_code")
            if not isinstance(symbol, str) or not symbol:
                continue

            quantity = _safe_float(row.get("quantity")) or _safe_float(row.get("quantity_available")) or 0.0
            quote_symbol = symbol_to_quote_symbol.get(symbol, symbol)
            quote_row = quote_by_symbol.get(quote_symbol.upper(), {})
            quote_payload = quote_row.get("quote") if isinstance(quote_row, dict) else {}
            quote_payload = quote_payload if isinstance(quote_payload, dict) else {}

            last_price = _safe_float(
                quote_payload.get("last_trade_price")
                or quote_payload.get("mark_price")
                or quote_payload.get("price")
                or quote_payload.get("bid_price")
                or quote_payload.get("ask_price")
            )

            computed_market_value = quantity * last_price if last_price is not None else None
            cost_basis = _safe_float(row.get("clearing_cost_basis")) or _safe_float(row.get("cost_basis"))
            if cost_basis is None:
                avg_buy = _safe_float(row.get("average_buy_price"))
                if avg_buy is not None and quantity:
                    cost_basis = avg_buy * quantity
            if cost_basis is None and isinstance(row.get("tax_lot_cost_bases"), list) and row["tax_lot_cost_bases"]:
                cost_basis = _safe_float(row["tax_lot_cost_bases"][0].get("clearing_book_cost_basis"))
            if cost_basis is None and isinstance(row.get("cost_bases"), list) and row["cost_bases"]:
                cost_basis = _safe_float(row["cost_bases"][0].get("direct_cost_basis"))

            if computed_market_value is None:
                computed_market_value = _safe_float(row.get("market_value"))

            unrealized = None
            unrealized_pct = None
            if computed_market_value is not None and cost_basis is not None:
                unrealized = computed_market_value - cost_basis
                if cost_basis:
                    unrealized_pct = (unrealized / cost_basis) * 100.0

            holdings_all.append(
                {
                    "symbol": symbol,
                    "asset_type": asset_type,
                    "quantity": quantity,
                    "last_price": last_price,
                    "market_value": computed_market_value,
                    "weight_pct": None,
                    "cost_basis": cost_basis,
                    "unrealized_pnl": unrealized,
                    "unrealized_pnl_pct": unrealized_pct,
                }
            )

        holdings_all.sort(key=lambda row: row.get("market_value") or 0.0, reverse=True)

        holdings_total_market = sum((row.get("market_value") or 0.0) for row in holdings_all)
        denominator = equity if equity and equity > 0 else holdings_total_market
        if denominator <= 0:
            denominator = holdings_total_market

        if denominator > 0:
            for row in holdings_all:
                market_val = row.get("market_value")
                if market_val is not None:
                    row["weight_pct"] = (market_val / denominator) * 100.0

        top3_pct = 0.0
        top5_pct = 0.0
        largest_position_pct = 0.0
        herfindahl_index = 0.0
        if denominator > 0:
            shares = [(row.get("market_value") or 0.0) / denominator for row in holdings_all]
            if shares:
                largest_position_pct = max(shares) * 100.0
                top3_pct = sum(shares[:3]) * 100.0
                top5_pct = sum(shares[:5]) * 100.0
                herfindahl_index = sum((share * 100.0) ** 2 for share in shares)

        exposure_totals: dict[str, float] = {}
        for row in holdings_all:
            asset_type = row.get("asset_type") or "unknown"
            exposure_totals[asset_type] = exposure_totals.get(asset_type, 0.0) + (row.get("market_value") or 0.0)

        exposure: dict[str, Any] = {"by_asset_type": {}, "cash": {"value": cash, "weight_pct": None}}
        for asset_type, total_value in sorted(exposure_totals.items()):
            exposure["by_asset_type"][asset_type] = {
                "market_value": total_value,
                "weight_pct": (total_value / denominator) * 100.0 if denominator > 0 else None,
            }
        if cash is not None and denominator > 0:
            exposure["cash"]["weight_pct"] = (cash / denominator) * 100.0

        alerts: list[dict[str, Any]] = []
        if largest_position_pct > 35.0:
            alerts.append(
                {
                    "code": "LARGEST_POSITION_CONCENTRATION",
                    "value": largest_position_pct,
                    "message": "Largest position exceeds 35% of portfolio value",
                }
            )
        if top3_pct > 70.0:
            alerts.append(
                {
                    "code": "TOP3_CONCENTRATION",
                    "value": top3_pct,
                    "message": "Top 3 positions exceed 70% of portfolio value",
                }
            )
        if cash is not None and cash < 0:
            alerts.append(
                {
                    "code": "NEGATIVE_CASH",
                    "value": cash,
                    "message": "Cash balance is negative",
                }
            )

        allocation = holdings_all[:top] if include_holdings else []
        payload = {
            "account": {
                "equity": equity,
                "market_value": market_value,
                "cash": cash,
                "buying_power": buying_power,
                "withdrawable_amount": withdrawable,
                "margin_debit": margin_debit,
            },
            "allocation": allocation,
            "concentration": {
                "largest_position_pct": largest_position_pct,
                "top3_pct": top3_pct,
                "top5_pct": top5_pct,
                "herfindahl_index": herfindahl_index,
            },
            "exposure": exposure,
            "alerts": alerts,
            "generated_at": _now_utc_iso(),
        }
        return payload

    _run_command(ctx, "portfolio analyze", _do, provider="brokerage")


@orders_stock_app.command("place")
def orders_stock_place(
    ctx: typer.Context,
    symbol: str = typer.Option(..., "--symbol"),
    side: str = typer.Option(..., "--side"),
    order_type: str = typer.Option("market", "--type"),
    qty: float | None = typer.Option(None, "--qty"),
    notional_usd: float | None = typer.Option(None, "--notional-usd"),
    limit_price: float | None = typer.Option(None, "--limit-price"),
    stop_price: float | None = typer.Option(None, "--stop-price"),
    time_in_force: str = typer.Option("gtc", "--time-in-force"),
    extended_hours: bool = typer.Option(False, "--extended-hours"),
    live_confirm_token: str | None = typer.Option(None, "--live-confirm-token"),
) -> None:
    runtime = _runtime(ctx)

    def _do():
        runtime.safety.require_live_authorization(live_confirm_token)
        intent = OrderIntentStock(
            symbol=symbol,
            side=side.lower(),
            order_type=order_type.lower(),
            quantity=qty,
            notional_usd=notional_usd,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=time_in_force.lower(),
            extended_hours=extended_hours,
        )
        check = runtime.safety.enforce(intent)
        result = runtime.brokerage_provider.place_order(intent)
        runtime.safety.record_notional(check.estimated_notional)
        return result.model_dump(mode="python")

    _run_command(ctx, "orders stock place", _do, provider="brokerage")


@orders_crypto_app.command("place")
def orders_crypto_place(
    ctx: typer.Context,
    symbol: str = typer.Option(..., "--symbol"),
    side: str = typer.Option(..., "--side"),
    order_type: str = typer.Option("market", "--type"),
    amount_in: str = typer.Option("quantity", "--amount-in"),
    qty: float | None = typer.Option(None, "--qty"),
    notional_usd: float | None = typer.Option(None, "--notional-usd"),
    limit_price: float | None = typer.Option(None, "--limit-price"),
    time_in_force: str = typer.Option("gtc", "--time-in-force"),
    live_confirm_token: str | None = typer.Option(None, "--live-confirm-token"),
) -> None:
    runtime = _runtime(ctx)
    provider = _resolve_provider(runtime, symbol=symbol)

    def _do():
        runtime.safety.require_live_authorization(live_confirm_token)
        intent = OrderIntentCrypto(
            symbol=symbol,
            side=side.lower(),
            order_type=order_type.lower(),
            amount_in=amount_in.lower(),
            quantity=qty,
            notional_usd=notional_usd,
            limit_price=limit_price,
            time_in_force=time_in_force.lower(),
        )
        check = runtime.safety.enforce(intent)
        result = provider.place_order(intent)
        runtime.safety.record_notional(check.estimated_notional)
        return result.model_dump(mode="python")

    _run_command(ctx, "orders crypto place", _do, provider=provider.name)


@orders_app.command("get")
def orders_get(
    ctx: typer.Context,
    order_id: str = typer.Argument(...),
    asset_type: str | None = typer.Option(None, "--asset-type", help="stock|option|crypto"),
) -> None:
    runtime = _runtime(ctx)

    provider = runtime.brokerage_provider
    if runtime.provider_choice == "crypto" or (
        runtime.provider_choice == "auto" and asset_type == "crypto" and runtime.auth.crypto_status().authenticated
    ):
        provider = runtime.crypto_provider

    def _do():
        return provider.get_order(order_id, asset_type=asset_type)

    _run_command(ctx, "orders get", _do, provider=provider.name)


@orders_app.command("cancel")
def orders_cancel(
    ctx: typer.Context,
    order_id: str = typer.Argument(...),
    asset_type: str | None = typer.Option(None, "--asset-type", help="stock|option|crypto"),
) -> None:
    runtime = _runtime(ctx)

    provider = runtime.brokerage_provider
    if runtime.provider_choice == "crypto" or (
        runtime.provider_choice == "auto" and asset_type == "crypto" and runtime.auth.crypto_status().authenticated
    ):
        provider = runtime.crypto_provider

    def _do():
        return provider.cancel_order(order_id, asset_type=asset_type)

    _run_command(ctx, "orders cancel", _do, provider=provider.name)


@orders_app.command("list")
def orders_list(
    ctx: typer.Context,
    open_only: bool = typer.Option(False, "--open", help="Only open orders"),
    asset_type: str | None = typer.Option(None, "--asset-type", help="stock|option|crypto"),
) -> None:
    runtime = _runtime(ctx)

    provider = runtime.brokerage_provider
    if runtime.provider_choice == "crypto" or (
        runtime.provider_choice == "auto" and asset_type == "crypto" and runtime.auth.crypto_status().authenticated
    ):
        provider = runtime.crypto_provider

    def _do():
        return provider.list_orders(
            open_only=open_only,
            asset_type=asset_type,
            symbol_resolve_limit=runtime.limit,
        )

    _run_command(ctx, "orders list", _do, provider=provider.name)


@options_app.command("chains")
def options_chains(ctx: typer.Context, symbol: str = typer.Argument(...)) -> None:
    runtime = _runtime(ctx)

    def _do():
        return runtime.brokerage_provider.option_chains(symbol)

    _run_command(ctx, "options chains", _do, provider="brokerage")


@options_app.command("expirations")
def options_expirations(ctx: typer.Context, symbol: str = typer.Argument(...)) -> None:
    runtime = _runtime(ctx)

    def _do():
        expirations = runtime.brokerage_provider.option_expirations(symbol)
        return {"symbol": symbol, "expiration_dates": expirations}

    _run_command(ctx, "options expirations", _do, provider="brokerage")


@options_app.command("strikes")
def options_strikes(
    ctx: typer.Context,
    symbol: str = typer.Argument(...),
    expiration_date: str = typer.Option(..., "--expiration-date"),
    option_type: str = typer.Option("both", "--option-type"),
) -> None:
    runtime = _runtime(ctx)

    def _do():
        strikes = runtime.brokerage_provider.option_strikes(
            symbol=symbol,
            expiration_date=expiration_date,
            option_type=option_type,
        )
        return {
            "symbol": symbol,
            "expiration_date": expiration_date,
            "option_type": option_type,
            "strikes": strikes,
        }

    _run_command(ctx, "options strikes", _do, provider="brokerage")


@options_contracts_app.command("find")
def options_contracts_find(
    ctx: typer.Context,
    symbol: str = typer.Option(..., "--symbol"),
    expiration_date: str | None = typer.Option(None, "--expiration-date"),
    strike: float | None = typer.Option(None, "--strike"),
    option_type: str | None = typer.Option(None, "--option-type"),
) -> None:
    runtime = _runtime(ctx)

    def _do():
        return runtime.brokerage_provider.option_contracts_find(
            symbol=symbol,
            expiration_date=expiration_date,
            strike_price=strike,
            option_type=option_type,
        )

    _run_command(ctx, "options contracts find", _do, provider="brokerage")


@options_quotes_app.command("get")
def options_quotes_get(
    ctx: typer.Context,
    symbol: str = typer.Option(..., "--symbol"),
    expiration_date: str = typer.Option(..., "--expiration-date"),
    strike: float = typer.Option(..., "--strike"),
    option_type: str = typer.Option(..., "--option-type"),
) -> None:
    runtime = _runtime(ctx)

    def _do():
        return runtime.brokerage_provider.option_quote_get(
            symbol=symbol,
            expiration_date=expiration_date,
            strike_price=strike,
            option_type=option_type,
        )

    _run_command(ctx, "options quotes get", _do, provider="brokerage")


@options_quotes_app.command("list")
def options_quotes_list(
    ctx: typer.Context,
    symbol: str = typer.Option(..., "--symbol"),
    expiration_date: str = typer.Option(..., "--expiration-date"),
    option_type: str = typer.Option("both", "--option-type"),
    min_oi: int | None = typer.Option(None, "--min-oi"),
    min_volume: int | None = typer.Option(None, "--min-volume"),
    delta_min: float | None = typer.Option(None, "--delta-min"),
    delta_max: float | None = typer.Option(None, "--delta-max"),
    iv_min: float | None = typer.Option(None, "--iv-min"),
    iv_max: float | None = typer.Option(None, "--iv-max"),
    sort_by: str = typer.Option("strike", "--sort", help="strike|delta|iv|open_interest|volume"),
    descending: bool = typer.Option(False, "--descending"),
    query_limit: int | None = typer.Option(None, "--query-limit"),
    offset: int = typer.Option(0, "--offset"),
) -> None:
    runtime = _runtime(ctx)

    def _do():
        if query_limit is not None and query_limit < 1:
            raise CLIError(code=ErrorCode.VALIDATION_ERROR, message="--query-limit must be >= 1")
        if offset < 0:
            raise CLIError(code=ErrorCode.VALIDATION_ERROR, message="--offset must be >= 0")

        rows = runtime.brokerage_provider.option_quotes_list(
            symbol=symbol,
            expiration_date=expiration_date,
            option_type=option_type,
        )

        filtered: list[dict[str, Any]] = []
        for row in rows:
            open_interest = _safe_float(row.get("open_interest"))
            volume = _safe_float(row.get("volume"))
            delta = _safe_float(row.get("delta"))
            iv = _safe_float(row.get("implied_volatility"))

            if min_oi is not None and (open_interest is None or open_interest < min_oi):
                continue
            if min_volume is not None and (volume is None or volume < min_volume):
                continue
            if delta_min is not None and (delta is None or delta < delta_min):
                continue
            if delta_max is not None and (delta is None or delta > delta_max):
                continue
            if iv_min is not None and (iv is None or iv < iv_min):
                continue
            if iv_max is not None and (iv is None or iv > iv_max):
                continue

            filtered.append(row)

        sort_key_map = {
            "strike": "strike_price",
            "delta": "delta",
            "iv": "implied_volatility",
            "open_interest": "open_interest",
            "volume": "volume",
        }
        sort_field = sort_key_map.get(sort_by)
        if sort_field is None:
            raise CLIError(
                code=ErrorCode.VALIDATION_ERROR,
                message="--sort must be one of strike|delta|iv|open_interest|volume",
            )

        filtered.sort(
            key=lambda row: _safe_float(row.get(sort_field)) if _safe_float(row.get(sort_field)) is not None else float("-inf"),
            reverse=descending,
        )

        total = len(filtered)
        sliced = filtered[offset:]
        if query_limit is not None:
            sliced = sliced[:query_limit]

        return CommandOutput(
            data=sliced,
            meta_updates=_query_meta(total_count=total, returned_count=len(sliced), offset=offset),
        )

    _run_command(ctx, "options quotes list", _do, provider="brokerage")


@options_orders_place_app.command("single")
def options_orders_place_single(
    ctx: typer.Context,
    side: str = typer.Option(..., "--side"),
    order_type: str = typer.Option("limit", "--type"),
    position_effect: str = typer.Option(..., "--position-effect"),
    credit_or_debit: str = typer.Option(..., "--credit-or-debit"),
    symbol: str = typer.Option(..., "--symbol"),
    quantity: int = typer.Option(..., "--qty"),
    expiration_date: str = typer.Option(..., "--expiration-date"),
    strike: float = typer.Option(..., "--strike"),
    option_type: str = typer.Option("both", "--option-type"),
    price: float | None = typer.Option(None, "--price"),
    limit_price: float | None = typer.Option(None, "--limit-price"),
    stop_price: float | None = typer.Option(None, "--stop-price"),
    time_in_force: str = typer.Option("gtc", "--time-in-force"),
    live_confirm_token: str | None = typer.Option(None, "--live-confirm-token"),
) -> None:
    runtime = _runtime(ctx)

    def _do():
        runtime.safety.require_live_authorization(live_confirm_token)
        intent = OrderIntentOptionSingle(
            side=side.lower(),
            order_type=order_type.lower(),
            position_effect=position_effect.lower(),
            credit_or_debit=credit_or_debit.lower(),
            symbol=symbol,
            quantity=quantity,
            expiration_date=expiration_date,
            strike=strike,
            option_type=option_type.lower(),
            price=price,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=time_in_force.lower(),
        )
        check = runtime.safety.enforce(intent)
        result = runtime.brokerage_provider.place_order(intent)
        runtime.safety.record_notional(check.estimated_notional)
        return result.model_dump(mode="python")

    _run_command(ctx, "options orders place single", _do, provider="brokerage")


def _spread_legs(expiration_date: str, option_type: str, effect: str, short_strike: float, long_strike: float):
    return [
        OptionLeg(
            expirationDate=expiration_date,
            strike=short_strike,
            optionType=option_type,
            effect=effect,
            action="sell",
        ),
        OptionLeg(
            expirationDate=expiration_date,
            strike=long_strike,
            optionType=option_type,
            effect=effect,
            action="buy",
        ),
    ]


@options_orders_place_app.command("credit-spread")
def options_orders_place_credit_spread(
    ctx: typer.Context,
    symbol: str = typer.Option(..., "--symbol"),
    quantity: int = typer.Option(..., "--qty"),
    price: float = typer.Option(..., "--price"),
    expiration_date: str = typer.Option(..., "--expiration-date"),
    option_type: str = typer.Option(..., "--option-type"),
    effect: str = typer.Option("open", "--effect"),
    short_strike: float = typer.Option(..., "--short-strike"),
    long_strike: float = typer.Option(..., "--long-strike"),
    time_in_force: str = typer.Option("gtc", "--time-in-force"),
    live_confirm_token: str | None = typer.Option(None, "--live-confirm-token"),
) -> None:
    runtime = _runtime(ctx)

    def _do():
        runtime.safety.require_live_authorization(live_confirm_token)
        intent = OrderIntentOptionSpread(
            direction="credit",
            symbol=symbol,
            quantity=quantity,
            price=price,
            spread=_spread_legs(
                expiration_date=expiration_date,
                option_type=option_type.lower(),
                effect=effect.lower(),
                short_strike=short_strike,
                long_strike=long_strike,
            ),
            time_in_force=time_in_force.lower(),
        )
        check = runtime.safety.enforce(intent)
        result = runtime.brokerage_provider.place_order(intent)
        runtime.safety.record_notional(check.estimated_notional)
        return result.model_dump(mode="python")

    _run_command(ctx, "options orders place credit-spread", _do, provider="brokerage")


@options_orders_place_app.command("debit-spread")
def options_orders_place_debit_spread(
    ctx: typer.Context,
    symbol: str = typer.Option(..., "--symbol"),
    quantity: int = typer.Option(..., "--qty"),
    price: float = typer.Option(..., "--price"),
    expiration_date: str = typer.Option(..., "--expiration-date"),
    option_type: str = typer.Option(..., "--option-type"),
    effect: str = typer.Option("open", "--effect"),
    short_strike: float = typer.Option(..., "--short-strike"),
    long_strike: float = typer.Option(..., "--long-strike"),
    time_in_force: str = typer.Option("gtc", "--time-in-force"),
    live_confirm_token: str | None = typer.Option(None, "--live-confirm-token"),
) -> None:
    runtime = _runtime(ctx)

    def _do():
        runtime.safety.require_live_authorization(live_confirm_token)
        intent = OrderIntentOptionSpread(
            direction="debit",
            symbol=symbol,
            quantity=quantity,
            price=price,
            spread=_spread_legs(
                expiration_date=expiration_date,
                option_type=option_type.lower(),
                effect=effect.lower(),
                short_strike=short_strike,
                long_strike=long_strike,
            ),
            time_in_force=time_in_force.lower(),
        )
        check = runtime.safety.enforce(intent)
        result = runtime.brokerage_provider.place_order(intent)
        runtime.safety.record_notional(check.estimated_notional)
        return result.model_dump(mode="python")

    _run_command(ctx, "options orders place debit-spread", _do, provider="brokerage")


@options_orders_app.command("get")
def options_orders_get(ctx: typer.Context, order_id: str = typer.Argument(...)) -> None:
    runtime = _runtime(ctx)

    def _do():
        return runtime.brokerage_provider.get_order(order_id, asset_type="option")

    _run_command(ctx, "options orders get", _do, provider="brokerage")


@options_orders_app.command("cancel")
def options_orders_cancel(ctx: typer.Context, order_id: str = typer.Argument(...)) -> None:
    runtime = _runtime(ctx)

    def _do():
        return runtime.brokerage_provider.cancel_order(order_id, asset_type="option")

    _run_command(ctx, "options orders cancel", _do, provider="brokerage")


@options_orders_app.command("list")
def options_orders_list(
    ctx: typer.Context,
    open_only: bool = typer.Option(False, "--open", help="Only open option orders"),
    symbol: str | None = typer.Option(None, "--symbol"),
    state: str | None = typer.Option(None, "--state"),
    strategy: str | None = typer.Option(None, "--strategy"),
    from_date: str | None = typer.Option(None, "--from-date"),
    to_date: str | None = typer.Option(None, "--to-date"),
    query_limit: int | None = typer.Option(None, "--query-limit"),
    offset: int = typer.Option(0, "--offset"),
    sort_by: str = typer.Option("created_at", "--sort", help="created_at|updated_at"),
    descending: bool = typer.Option(False, "--descending"),
) -> None:
    runtime = _runtime(ctx)

    def _do():
        if query_limit is not None and query_limit < 1:
            raise CLIError(code=ErrorCode.VALIDATION_ERROR, message="--query-limit must be >= 1")
        if offset < 0:
            raise CLIError(code=ErrorCode.VALIDATION_ERROR, message="--offset must be >= 0")

        from_day = _parse_yyyy_mm_dd(from_date, arg_name="--from-date") if from_date else None
        to_day = _parse_yyyy_mm_dd(to_date, arg_name="--to-date") if to_date else None
        if from_day and to_day and from_day > to_day:
            raise CLIError(code=ErrorCode.VALIDATION_ERROR, message="--from-date cannot be after --to-date")

        rows = runtime.brokerage_provider.list_orders(
            open_only=open_only,
            asset_type="option",
            symbol_resolve_limit=runtime.limit,
        )

        filtered: list[dict[str, Any]] = []
        symbol_filter = symbol.lower() if symbol else None
        state_filter = state.lower() if state else None
        strategy_filter = strategy.lower() if strategy else None

        for row in rows:
            if not isinstance(row, dict):
                continue

            chain_symbol = str(row.get("chain_symbol") or row.get("symbol") or "").lower()
            if symbol_filter and symbol_filter != chain_symbol:
                continue

            row_state = str(row.get("state") or row.get("derived_state") or "").lower()
            if state_filter and state_filter not in row_state:
                continue

            if strategy_filter:
                strategy_blob = " ".join(
                    [
                        str(row.get("strategy") or ""),
                        str(row.get("opening_strategy") or ""),
                        str(row.get("closing_strategy") or ""),
                    ]
                ).lower()
                if strategy_filter not in strategy_blob:
                    continue

            created_dt = _parse_iso_timestamp(row.get("created_at"))
            if from_day and (created_dt is None or created_dt.date() < from_day):
                continue
            if to_day and (created_dt is None or created_dt.date() > to_day):
                continue

            filtered.append(row)

        if sort_by not in {"created_at", "updated_at"}:
            raise CLIError(code=ErrorCode.VALIDATION_ERROR, message="--sort must be created_at or updated_at")

        filtered.sort(
            key=lambda row: _parse_iso_timestamp(row.get(sort_by)) or datetime.min.replace(tzinfo=UTC),
            reverse=descending,
        )

        total = len(filtered)
        sliced = filtered[offset:]
        if query_limit is not None:
            sliced = sliced[:query_limit]

        return CommandOutput(
            data=sliced,
            meta_updates=_query_meta(total_count=total, returned_count=len(sliced), offset=offset),
        )

    _run_command(ctx, "options orders list", _do, provider="brokerage")


@app.command("doctor")
def doctor(ctx: typer.Context) -> None:
    runtime = _runtime(ctx)

    def _do():
        brokerage_status = runtime.auth.brokerage_status()
        crypto_status = runtime.crypto_provider.auth_status()

        checks = {
            "paths": {
                "config": str(runtime.config.paths.config_path),
                "session_dir": str(runtime.config.paths.session_dir),
                "state_db": str(runtime.config.paths.state_db_path),
            },
            "provider_default": runtime.config.app.provider_default,
            "safety": runtime.config.app.safety.model_dump(mode="python"),
            "live_unlock": runtime.safety.live_unlock_status(),
            "auth": {
                "brokerage": brokerage_status.model_dump(mode="python"),
                "crypto": crypto_status.model_dump(mode="python"),
            },
            "providers": {
                "brokerage_capabilities": runtime.brokerage_provider.capabilities().model_dump(mode="python"),
                "crypto_capabilities": runtime.crypto_provider.capabilities().model_dump(mode="python"),
            },
        }
        return checks

    _run_command(ctx, "doctor", _do)


if __name__ == "__main__":  # pragma: no cover
    app()
