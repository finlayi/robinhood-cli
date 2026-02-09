from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

import rhx.safety as safety_module
from rhx.config import SafetyConfig
from rhx.errors import CLIError, ErrorCode
from rhx.models import OrderIntentCrypto, OrderIntentOptionSingle, OrderIntentOptionSpread, OrderIntentStock, OptionLeg
from rhx.safety import SafetyEngine


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        del tz
        return cls(2026, 1, 1, 12, 0, 0)

    @classmethod
    def utcnow(cls):
        return cls(2026, 1, 1, 12, 0, 0)


class LaterDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        del tz
        return cls(2026, 1, 1, 12, 1, 0)

    @classmethod
    def utcnow(cls):
        return cls(2026, 1, 1, 12, 1, 0)


class OvernightDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        del tz
        return cls(2026, 1, 1, 1, 0, 0)

    @classmethod
    def utcnow(cls):
        return cls(2026, 1, 1, 1, 0, 0)


def test_live_mode_guard_and_toggle(tmp_path):
    cfg = SafetyConfig(live_mode=False)
    engine = SafetyEngine(db_path=tmp_path / "state.db", config=cfg)

    with pytest.raises(CLIError) as exc:
        engine.require_live_mode()
    assert exc.value.code == ErrorCode.LIVE_MODE_OFF

    engine.set_live_mode(True)
    engine.require_live_mode()


def test_live_unlock_token_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setattr(safety_module, "datetime", FrozenDateTime)

    engine = SafetyEngine(db_path=tmp_path / "state.db", config=SafetyConfig(live_mode=True))
    token, expires_at = engine.issue_live_unlock(ttl_seconds=30)
    assert token
    assert isinstance(expires_at, int)

    status = engine.live_unlock_status()
    assert status["active"] is True
    assert status["expires_at"] == expires_at

    engine.require_live_authorization(token)

    with pytest.raises(CLIError) as invalid:
        engine.require_live_authorization("wrong-token")
    assert invalid.value.code == ErrorCode.SAFETY_POLICY_BLOCK

    with pytest.raises(CLIError) as missing:
        engine.require_live_authorization(None)
    assert missing.value.code == ErrorCode.SAFETY_POLICY_BLOCK

    engine.clear_live_unlock()
    status_after = engine.live_unlock_status()
    assert status_after == {"active": False, "expires_at": None}


def test_live_unlock_token_expiry(monkeypatch, tmp_path):
    monkeypatch.setattr(safety_module, "datetime", FrozenDateTime)
    engine = SafetyEngine(db_path=tmp_path / "state.db", config=SafetyConfig(live_mode=True))
    token, _ = engine.issue_live_unlock(ttl_seconds=1)

    monkeypatch.setattr(safety_module, "datetime", LaterDateTime)
    with pytest.raises(CLIError) as expired:
        engine.require_live_authorization(token)
    assert expired.value.code == ErrorCode.SAFETY_POLICY_BLOCK


def test_live_unlock_requires_existing_token_row(tmp_path):
    engine = SafetyEngine(db_path=tmp_path / "state.db", config=SafetyConfig(live_mode=True))
    with pytest.raises(CLIError) as exc:
        engine.require_live_authorization("some-token")
    assert exc.value.code == ErrorCode.SAFETY_POLICY_BLOCK


def test_symbol_allow_and_block(tmp_path):
    cfg = SafetyConfig(allow_symbols=["AAPL"], block_symbols=["TSLA"])
    engine = SafetyEngine(db_path=tmp_path / "state.db", config=cfg)

    engine.check_symbol("aapl")

    with pytest.raises(CLIError):
        engine.check_symbol("msft")

    with pytest.raises(CLIError):
        engine.check_symbol("tsla")


def test_symbol_block_without_allow_list(tmp_path):
    cfg = SafetyConfig(block_symbols=["TSLA"])
    engine = SafetyEngine(db_path=tmp_path / "state.db", config=cfg)

    with pytest.raises(CLIError) as exc:
        engine.check_symbol("tsla")
    assert exc.value.code == ErrorCode.SAFETY_POLICY_BLOCK


def test_trading_window_validation_and_outside(monkeypatch, tmp_path):
    monkeypatch.setattr(safety_module, "datetime", FrozenDateTime)

    cfg_bad = SafetyConfig(trading_window="invalid")
    engine_bad = SafetyEngine(db_path=tmp_path / "bad.db", config=cfg_bad)
    with pytest.raises(CLIError) as exc_bad:
        engine_bad.check_trading_window()
    assert exc_bad.value.code == ErrorCode.VALIDATION_ERROR

    cfg_outside = SafetyConfig(trading_window="09:00-10:00")
    engine_outside = SafetyEngine(db_path=tmp_path / "outside.db", config=cfg_outside)
    with pytest.raises(CLIError) as exc_outside:
        engine_outside.check_trading_window()
    assert exc_outside.value.code == ErrorCode.SAFETY_POLICY_BLOCK


def test_trading_window_value_error_and_overnight(monkeypatch, tmp_path):
    monkeypatch.setattr(safety_module, "datetime", FrozenDateTime)

    cfg_value_error = SafetyConfig(trading_window="09:ab-10:00")
    engine_value_error = SafetyEngine(db_path=tmp_path / "value-error.db", config=cfg_value_error)
    with pytest.raises(CLIError) as exc_bad:
        engine_value_error.check_trading_window()
    assert exc_bad.value.code == ErrorCode.VALIDATION_ERROR

    monkeypatch.setattr(safety_module, "datetime", OvernightDateTime)
    cfg_overnight = SafetyConfig(trading_window="23:00-02:00")
    engine_overnight = SafetyEngine(db_path=tmp_path / "overnight.db", config=cfg_overnight)
    engine_overnight.check_trading_window()


def test_enforce_notional_limits_and_daily_tracking(monkeypatch, tmp_path):
    monkeypatch.setattr(safety_module, "datetime", FrozenDateTime)

    cfg = SafetyConfig(max_order_notional=500, max_daily_notional=700)
    engine = SafetyEngine(db_path=tmp_path / "state.db", config=cfg)

    ok = OrderIntentStock(symbol="AAPL", side="buy", order_type="limit", quantity=1, limit_price=100)
    result = engine.enforce(ok)
    assert result.estimated_notional == 100

    engine.record_notional(650)
    with pytest.raises(CLIError) as exc:
        engine.enforce(ok)
    assert exc.value.code == ErrorCode.SAFETY_POLICY_BLOCK

    too_big = OrderIntentStock(symbol="AAPL", side="buy", order_type="limit", quantity=10, limit_price=60)
    with pytest.raises(CLIError) as exc2:
        engine.enforce(too_big)
    assert exc2.value.code == ErrorCode.SAFETY_POLICY_BLOCK


def test_estimate_notional_by_intent_type(tmp_path):
    engine = SafetyEngine(db_path=tmp_path / "state.db", config=SafetyConfig())

    stock = OrderIntentStock(symbol="AAPL", side="buy", order_type="limit", quantity=2, limit_price=10)
    crypto = OrderIntentCrypto(symbol="BTC-USD", side="buy", order_type="limit", amount_in="quantity", quantity=0.5, limit_price=100)
    option_single = OrderIntentOptionSingle(
        side="buy",
        order_type="limit",
        position_effect="open",
        credit_or_debit="debit",
        symbol="AAPL",
        quantity=2,
        expiration_date="2026-12-18",
        strike=200,
        price=1.5,
    )
    spread = OrderIntentOptionSpread(
        direction="credit",
        symbol="AAPL",
        quantity=2,
        price=1.25,
        spread=[
            OptionLeg(expirationDate="2026-12-18", strike=200, optionType="call", effect="open", action="sell"),
            OptionLeg(expirationDate="2026-12-18", strike=205, optionType="call", effect="open", action="buy"),
        ],
    )

    assert engine.estimate_notional(stock) == 20
    assert engine.estimate_notional(crypto) == 50
    assert engine.estimate_notional(option_single) == 300
    assert engine.estimate_notional(spread) == 250


def test_estimate_notional_additional_branches(tmp_path):
    engine = SafetyEngine(db_path=tmp_path / "state.db", config=SafetyConfig())

    stock_notional = OrderIntentStock(symbol="AAPL", side="buy", order_type="market", notional_usd=55)
    stock_stop = OrderIntentStock(symbol="AAPL", side="buy", order_type="market", quantity=2, stop_price=12)
    crypto_notional = OrderIntentCrypto(symbol="BTC-USD", side="buy", order_type="market", amount_in="price", notional_usd=20)

    assert engine.estimate_notional(stock_notional) == 55
    assert engine.estimate_notional(stock_stop) == 24
    assert engine.estimate_notional(crypto_notional) == 20
    assert engine.estimate_notional(object()) == 0


def test_connect_rolls_back_on_error(tmp_path):
    engine = SafetyEngine(db_path=tmp_path / "state.db", config=SafetyConfig())
    with pytest.raises(sqlite3.OperationalError):
        with engine._connect() as conn:
            conn.execute("INSERT INTO does_not_exist VALUES (1)")
