from __future__ import annotations

from typing import Any, Callable

from simulation.models import AccountState, Order, OrderRequest, Position, Tick, Trade


SendOrder = Callable[[OrderRequest], Order]
LogCallback = Callable[[str], None]


class BaseStrategy:
    """Base class for local paper-trading strategies."""

    def __init__(self, name: str, send_order: SendOrder, log: LogCallback | None = None) -> None:
        self.name = name
        self.send_order = send_order
        self.log = log or (lambda message: None)
        self.active = False
        self.parameters: dict[str, Any] = {}

    def on_init(self) -> None:
        pass

    def on_start(self) -> None:
        self.active = True

    def on_stop(self) -> None:
        self.active = False

    def on_tick(self, tick: Tick) -> None:
        pass

    def on_order(self, order: Order) -> None:
        pass

    def on_trade(self, trade: Trade) -> None:
        pass

    def on_account(self, account: AccountState) -> None:
        pass

    def on_position(self, position: Position) -> None:
        pass

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "active": self.active,
            "parameters": self.parameters,
        }
