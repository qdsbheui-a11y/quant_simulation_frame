from __future__ import annotations

from data.models import TickData
from execution.models import Direction, Order, OrderType, SimulationConfig


class Matcher:
    """Deterministic tick-level matcher used by the simulation exchange."""

    def __init__(self, config: SimulationConfig | None = None) -> None:
        self.config = config or SimulationConfig()

    def get_match_price(self, order: Order, tick: TickData) -> float | None:
        if order.order_type == OrderType.MARKET:
            if self.config.market_order_price_source == "last":
                base_price = tick.last_price
            elif order.direction == Direction.LONG:
                base_price = tick.ask_price_1 or tick.last_price
            else:
                base_price = tick.bid_price_1 or tick.last_price
            return self._apply_slippage(order.direction, base_price)

        if order.direction == Direction.LONG:
            executable = tick.ask_price_1 > 0 and order.price >= tick.ask_price_1
            base_price = tick.ask_price_1 or tick.last_price
        else:
            executable = tick.bid_price_1 > 0 and order.price <= tick.bid_price_1
            base_price = tick.bid_price_1 or tick.last_price

        if not executable:
            return None
        return self._apply_slippage(order.direction, base_price)

    def _apply_slippage(self, direction: Direction, price: float) -> float:
        if direction == Direction.LONG:
            return round(price + self.config.slippage, 8)
        return round(price - self.config.slippage, 8)
