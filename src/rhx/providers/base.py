from __future__ import annotations

from typing import Any, Protocol

from rhx.models import (
    AuthStatus,
    CapabilitySet,
    OrderIntentCrypto,
    OrderIntentOptionSingle,
    OrderIntentOptionSpread,
    OrderIntentStock,
    OrderResult,
)


OrderIntent = OrderIntentStock | OrderIntentCrypto | OrderIntentOptionSingle | OrderIntentOptionSpread


class BrokerProvider(Protocol):
    name: str

    def capabilities(self) -> CapabilitySet: ...

    def auth_status(self) -> AuthStatus: ...

    def account_summary(self) -> dict[str, Any]: ...

    def positions(self) -> list[dict[str, Any]]: ...

    def quote(self, symbol: str) -> dict[str, Any]: ...

    def place_order(self, intent: OrderIntent) -> OrderResult: ...

    def cancel_order(self, order_id: str, asset_type: str | None = None) -> dict[str, Any]: ...

    def get_order(self, order_id: str, asset_type: str | None = None) -> dict[str, Any]: ...

    def list_orders(
        self,
        open_only: bool = False,
        asset_type: str | None = None,
        symbol_resolve_limit: int | None = None,
    ) -> list[dict[str, Any]]: ...
