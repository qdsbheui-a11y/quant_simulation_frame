from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Protocol

from data.models import BarData, TickData
from execution.models import Direction, Offset, OrderIntent, OrderRequest, OrderType


class OrderSubmitter(Protocol):
    def __call__(self, intent: OrderIntent) -> object:
        """Submit a strategy intent to the active runtime execution adapter."""


@dataclass(slots=True)
class StrategyContext:
    """Runtime services exposed to a strategy without tying it to an engine."""

    strategy_id: str
    submit_order_intent: OrderSubmitter
    metadata: dict[str, object] = field(default_factory=dict)

    def submit(self, intent: OrderIntent) -> object:
        if intent.strategy_id is None:
            intent.strategy_id = self.strategy_id
        return self.submit_order_intent(intent)


class BaseStrategy:
    """Unified strategy API consumed by BacktestRuntime and SimulationRuntime."""

    def __init__(self, strategy_id: str | None = None) -> None:
        self.strategy_id = strategy_id or self.__class__.__name__
        self.context: StrategyContext | None = None

    def bind(self, context: StrategyContext) -> None:
        self.context = context

    def on_start(self) -> None:
        """Called once before runtime data replay/live consumption starts."""

    def on_stop(self) -> None:
        """Called once after runtime data consumption stops."""

    def on_tick(self, tick: TickData) -> Iterable[OrderIntent]:
        return []

    def on_bar(self, bar: BarData) -> Iterable[OrderIntent]:
        return []

    def buy(self, vt_symbol: str, price: float, volume: float, order_type: OrderType = OrderType.LIMIT) -> OrderIntent:
        return self._intent(vt_symbol, Direction.LONG, Offset.OPEN, price, volume, order_type)

    def sell(self, vt_symbol: str, price: float, volume: float, order_type: OrderType = OrderType.LIMIT) -> OrderIntent:
        return self._intent(vt_symbol, Direction.SHORT, Offset.CLOSE, price, volume, order_type)

    def short(self, vt_symbol: str, price: float, volume: float, order_type: OrderType = OrderType.LIMIT) -> OrderIntent:
        return self._intent(vt_symbol, Direction.SHORT, Offset.OPEN, price, volume, order_type)

    def cover(self, vt_symbol: str, price: float, volume: float, order_type: OrderType = OrderType.LIMIT) -> OrderIntent:
        return self._intent(vt_symbol, Direction.LONG, Offset.CLOSE, price, volume, order_type)

    def submit(self, intent: OrderIntent) -> object:
        if self.context is None:
            raise RuntimeError("strategy is not bound to a StrategyContext")
        return self.context.submit(intent)

    def _intent(
        self,
        vt_symbol: str,
        direction: Direction,
        offset: Offset,
        price: float,
        volume: float,
        order_type: OrderType,
    ) -> OrderIntent:
        return OrderIntent(
            vt_symbol=vt_symbol,
            direction=direction,
            offset=offset,
            price=price,
            volume=volume,
            order_type=order_type,
            strategy_id=self.strategy_id,
        )


def intent_to_request(intent: OrderIntent) -> OrderRequest:
    return OrderRequest.from_intent(intent)
