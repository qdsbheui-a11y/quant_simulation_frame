from __future__ import annotations

from typing import Any

from data.models import TickData
from simulation.engine import SimulationEngine
from simulation.models import Direction, Offset, OrderRequest, OrderType
from strategy.intent import OrderAction, OrderIntent

from .base import Execution


ACTION_MAPPING: dict[OrderAction, tuple[Direction, Offset]] = {
    OrderAction.BUY_OPEN: (Direction.LONG, Offset.OPEN),
    OrderAction.SELL_CLOSE: (Direction.SHORT, Offset.CLOSE),
    OrderAction.SELL_OPEN: (Direction.SHORT, Offset.OPEN),
    OrderAction.BUY_CLOSE: (Direction.LONG, Offset.CLOSE),
}


class SimulationExecution(Execution):
    """Execution adapter that routes strategy intents to SimulationEngine."""

    def __init__(self, simulation_engine: SimulationEngine) -> None:
        self.simulation_engine = simulation_engine

    def send_intent(self, intent: OrderIntent) -> Any:
        direction, offset = ACTION_MAPPING[intent.action]

        order_type = OrderType(intent.order_type.upper())
        price = intent.price if intent.price is not None else 0.0

        request = OrderRequest(
            vt_symbol=intent.vt_symbol,
            direction=direction,
            offset=offset,
            price=price,
            volume=intent.volume,
            order_type=order_type,
        )
        return self.simulation_engine.submit_order(request)

    def on_tick(self, tick: TickData) -> Any:
        return self.simulation_engine.on_tick(tick.to_simulation_tick())

    def get_account(self) -> Any:
        return self.simulation_engine.account

    def get_position(self, vt_symbol: str) -> Any:
        return self.simulation_engine.positions.get(vt_symbol)

    def get_orders(self) -> Any:
        return list(self.simulation_engine.orders.values())

    def get_trades(self) -> Any:
        return list(self.simulation_engine.trades.values())
