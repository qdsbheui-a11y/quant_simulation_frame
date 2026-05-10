from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from simulation.engine import SimulationEngine
from simulation.models import Direction, Offset, OrderRequest, OrderType, Tick


@dataclass(slots=True)
class RealtimeStrategyContext:
    engine: SimulationEngine


class RealtimeStrategy(Protocol):
    def on_tick(self, tick: Tick, context: RealtimeStrategyContext) -> list[OrderRequest]:
        ...


@dataclass(slots=True)
class BuyAndHoldOnFirstTickStrategy:
    """Submit one market buy order per symbol after the first usable tick.

    This intentionally conservative strategy is mainly a live-tick simulation
    smoke test: it verifies that real-time ticks can trigger strategy logic and
    automatic simulated orders without submitting on every tick.
    """

    symbols: set[str]
    volume: float = 1.0
    order_type: OrderType = OrderType.MARKET
    submitted_symbols: set[str] = field(default_factory=set)

    def on_tick(self, tick: Tick, context: RealtimeStrategyContext) -> list[OrderRequest]:
        if tick.vt_symbol not in self.symbols:
            return []
        if tick.vt_symbol in self.submitted_symbols:
            return []
        if tick.last_price <= 0:
            return []

        position = context.engine.positions.get(tick.vt_symbol)
        if position and position.long_volume > 0:
            self.submitted_symbols.add(tick.vt_symbol)
            return []

        self.submitted_symbols.add(tick.vt_symbol)
        return [
            OrderRequest(
                vt_symbol=tick.vt_symbol,
                direction=Direction.LONG,
                offset=Offset.OPEN,
                price=max(tick.ask_price_1, tick.last_price, 1e-12),
                volume=self.volume,
                order_type=self.order_type,
            )
        ]


class RealtimeStrategyRunner:
    def __init__(self, strategy: RealtimeStrategy, engine: SimulationEngine) -> None:
        self.strategy = strategy
        self.context = RealtimeStrategyContext(engine=engine)
        self.enabled = True
        self.generated_orders = 0
        self.last_error: str | None = None

    def on_tick(self, tick: Tick) -> list[OrderRequest]:
        if not self.enabled:
            return []
        try:
            requests = self.strategy.on_tick(tick, self.context)
            self.generated_orders += len(requests)
            self.last_error = None
            return requests
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return []
