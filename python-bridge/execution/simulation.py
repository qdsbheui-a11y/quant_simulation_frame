from __future__ import annotations

from data.models import TickData
from execution.models import Order, OrderIntent, OrderRequest, SimulationConfig
from simulation.engine import SimulationEngine


class SimulationExecution:
    """Execution adapter: OrderIntent -> OrderRequest -> SimulationEngine."""

    def __init__(self, engine: SimulationEngine | None = None, config: SimulationConfig | None = None) -> None:
        self.engine = engine or SimulationEngine(config)

    def on_tick(self, tick: TickData) -> None:
        self.engine.on_tick(tick)

    def submit_order_intent(self, intent: OrderIntent) -> Order:
        return self.engine.submit_order(OrderRequest.from_intent(intent))

    def snapshot(self) -> dict:
        return self.engine.snapshot()
