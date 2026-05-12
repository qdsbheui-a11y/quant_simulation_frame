from __future__ import annotations

from typing import Any

from data.models import BarData, TickData


class BaseStrategy:
    """Base class for strategies that can run in multiple runtimes.

    A strategy should only depend on normalized market data and StrategyContext.
    It should not depend directly on Backtrader, a realtime gateway, or the
    simulation engine internals.
    """

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    def on_start(self) -> None:
        pass

    def on_stop(self) -> None:
        pass

    def on_tick(self, tick: TickData) -> None:
        pass

    def on_bar(self, bar: BarData) -> None:
        pass

    def on_order(self, order: Any) -> None:
        pass

    def on_trade(self, trade: Any) -> None:
        pass

    def on_account(self, account: Any) -> None:
        pass

    def on_position(self, position: Any) -> None:
        pass
