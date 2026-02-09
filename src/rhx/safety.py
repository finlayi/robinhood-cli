from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rhx.config import SafetyConfig
from rhx.errors import CLIError, ErrorCode
from rhx.models import (
    OrderIntentCrypto,
    OrderIntentOptionSingle,
    OrderIntentOptionSpread,
    OrderIntentStock,
)


@dataclass
class SafetyCheckResult:
    estimated_notional: float


class SafetyEngine:
    def __init__(self, db_path: Path, config: SafetyConfig) -> None:
        self.db_path = db_path
        self.config = config
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    @contextmanager
    def _connect(self):
        conn = self._conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_notional (
                    day TEXT PRIMARY KEY,
                    notional REAL NOT NULL
                )
                """
            )

    def set_live_mode(self, enabled: bool) -> None:
        self.config.live_mode = enabled

    def live_mode_enabled(self) -> bool:
        return bool(self.config.live_mode)

    def require_live_mode(self) -> None:
        if not self.live_mode_enabled():
            raise CLIError(
                code=ErrorCode.LIVE_MODE_OFF,
                message="Live mode is OFF. Enable with `rhx live on`.",
            )

    def check_symbol(self, symbol: str) -> None:
        normalized = symbol.upper()
        allow = {s.upper() for s in self.config.allow_symbols}
        block = {s.upper() for s in self.config.block_symbols}

        if allow and normalized not in allow:
            raise CLIError(
                code=ErrorCode.SAFETY_POLICY_BLOCK,
                message=f"Symbol {normalized} is not in allow list",
            )
        if normalized in block:
            raise CLIError(
                code=ErrorCode.SAFETY_POLICY_BLOCK,
                message=f"Symbol {normalized} is blocked by policy",
            )

    def check_trading_window(self) -> None:
        if not self.config.trading_window:
            return

        window = self.config.trading_window.strip()
        if "-" not in window:
            raise CLIError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Invalid trading_window format; expected HH:MM-HH:MM",
            )
        start_s, end_s = window.split("-", 1)
        now = datetime.now().time()

        try:
            start = datetime.strptime(start_s, "%H:%M").time()
            end = datetime.strptime(end_s, "%H:%M").time()
        except ValueError as exc:
            raise CLIError(
                code=ErrorCode.VALIDATION_ERROR,
                message=f"Invalid trading_window format: {exc}",
            ) from exc

        if start <= end:
            allowed = start <= now <= end
        else:
            allowed = now >= start or now <= end

        if not allowed:
            raise CLIError(
                code=ErrorCode.SAFETY_POLICY_BLOCK,
                message="Trading is outside configured trading_window",
            )

    def today_notional(self) -> float:
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        with self._connect() as conn:
            row = conn.execute("SELECT notional FROM daily_notional WHERE day = ?", (day,)).fetchone()
        return float(row[0]) if row else 0.0

    def record_notional(self, notional: float) -> None:
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO daily_notional(day, notional)
                VALUES (?, ?)
                ON CONFLICT(day) DO UPDATE SET notional = notional + excluded.notional
                """,
                (day, notional),
            )

    def estimate_notional(
        self,
        intent: OrderIntentStock | OrderIntentCrypto | OrderIntentOptionSingle | OrderIntentOptionSpread,
    ) -> float:
        if isinstance(intent, OrderIntentStock):
            if intent.notional_usd:
                return float(intent.notional_usd)
            if intent.quantity and intent.limit_price:
                return float(intent.quantity * intent.limit_price)
            if intent.quantity and intent.stop_price:
                return float(intent.quantity * intent.stop_price)
            return 0.0

        if isinstance(intent, OrderIntentCrypto):
            if intent.notional_usd:
                return float(intent.notional_usd)
            if intent.quantity and intent.limit_price:
                return float(intent.quantity * intent.limit_price)
            return 0.0

        if isinstance(intent, OrderIntentOptionSingle):
            px = intent.price if intent.price is not None else intent.limit_price
            return float((px or 0.0) * intent.quantity * 100)

        if isinstance(intent, OrderIntentOptionSpread):
            return float(intent.price * intent.quantity * 100)

        return 0.0

    def enforce(
        self,
        intent: OrderIntentStock | OrderIntentCrypto | OrderIntentOptionSingle | OrderIntentOptionSpread,
    ) -> SafetyCheckResult:
        symbol = getattr(intent, "symbol")
        self.check_symbol(symbol)
        self.check_trading_window()

        estimated = self.estimate_notional(intent)

        if self.config.max_order_notional is not None and estimated > self.config.max_order_notional:
            raise CLIError(
                code=ErrorCode.SAFETY_POLICY_BLOCK,
                message=(
                    f"Estimated order notional {estimated:.2f} exceeds max_order_notional "
                    f"{self.config.max_order_notional:.2f}"
                ),
            )

        if self.config.max_daily_notional is not None:
            projected = self.today_notional() + estimated
            if projected > self.config.max_daily_notional:
                raise CLIError(
                    code=ErrorCode.SAFETY_POLICY_BLOCK,
                    message=(
                        f"Projected daily notional {projected:.2f} exceeds max_daily_notional "
                        f"{self.config.max_daily_notional:.2f}"
                    ),
                )

        return SafetyCheckResult(estimated_notional=estimated)
