from __future__ import annotations

from typing import Any

from data.models import TickData
from strategy.intent import OrderIntent


class Execution:
    """Abstract execution interface used by StrategyContext.

    Runtime implementations should provide concrete adapters for backtest,
    realtime simulation, or future live trading gateways.
    """

    def send_intent(self, intent: OrderIntent) -> Any:
        raise NotImplementedError

    def on_tick(self, tick: TickData) -> Any:
        return None

    def get_account(self) -> Any:
        raise NotImplementedError

    def get_position(self, vt_symbol: str) -> Any:
        raise NotImplementedError

    def get_orders(self) -> Any:
        raise NotImplementedError

    def get_trades(self) -> Any:
        raise NotImplementedError
