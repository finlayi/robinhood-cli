from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
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


@dataclass
class AppRuntime:
    json_mode: bool
    provider_choice: str
    config: RuntimeConfig
    auth: AuthManager
    safety: SafetyEngine
    brokerage_provider: RobinStocksProvider
    crypto_provider: RobinhoodCryptoProvider


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
        data = func()
        emit_success(command, _serialize(data), runtime.json_mode, provider)
    except CLIError as err:
        emit_error(err, command, runtime.json_mode, provider)
        raise typer.Exit(err.exit_code)
    except ValidationError as err:
        cli_err = CLIError(code=ErrorCode.VALIDATION_ERROR, message=str(err))
        emit_error(cli_err, command, runtime.json_mode, provider)
        raise typer.Exit(cli_err.exit_code)
    except Exception as exc:  # pragma: no cover
        cli_err = map_unexpected_error(exc)
        emit_error(cli_err, command, runtime.json_mode, provider)
        raise typer.Exit(cli_err.exit_code)


@app.callback()
def main(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output"),
    profile: str = typer.Option("default", "--profile", help="Credential/profile namespace"),
    provider: str = typer.Option("auto", "--provider", help="Provider preference: auto|crypto|brokerage"),
    config: Path = typer.Option(default_config_path(), "--config", help="Config path"),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose logs"),
    no_color: bool = typer.Option(False, "--no-color", help="Disable color output"),
) -> None:
    del verbose
    del no_color

    runtime_cfg = load_runtime_config(config_path=config, profile=profile)
    auth = AuthManager(profile=profile, session_dir=runtime_cfg.paths.session_dir)
    safety = SafetyEngine(db_path=runtime_cfg.paths.state_db_path, config=runtime_cfg.app.safety)

    runtime = AppRuntime(
        json_mode=json_output,
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
        brokerage = runtime.auth.brokerage_status()
        crypto = runtime.crypto_provider.auth_status()
        return {
            "brokerage": brokerage.model_dump(mode="python"),
            "crypto": crypto.model_dump(mode="python"),
        }

    _run_command(ctx, "auth status", _do)


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
        return provider.list_orders(open_only=open_only, asset_type=asset_type)

    _run_command(ctx, "orders list", _do, provider=provider.name)


@options_app.command("chains")
def options_chains(ctx: typer.Context, symbol: str = typer.Argument(...)) -> None:
    runtime = _runtime(ctx)

    def _do():
        return runtime.brokerage_provider.option_chains(symbol)

    _run_command(ctx, "options chains", _do, provider="brokerage")


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
) -> None:
    runtime = _runtime(ctx)

    def _do():
        return runtime.brokerage_provider.list_orders(open_only=open_only, asset_type="option")

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
