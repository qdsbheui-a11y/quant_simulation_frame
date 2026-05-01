from __future__ import annotations

from .models import OrderRequest, OrderType, Side, Tick
from .sim_broker import SimBroker


class DemoBuyOnceStrategy:
    """Minimal strategy for smoke testing paper-trading plumbing."""

    def __init__(self, broker: SimBroker, strategy_id: str = "demo_buy_once", volume: float = 0.001) -> None:
        self.broker = broker
        self.strategy_id = strategy_id
        self.volume = volume
        self._ordered_symbols: set[str] = set()

    async def on_tick(self, tick: Tick) -> None:
        key = f"{tick.market.value}:{tick.exchange}:{tick.symbol}"
        if key in self._ordered_symbols:
            return

        price = tick.ask_price or tick.last_price
        if price is None:
            return

        await self.broker.send_order(
            OrderRequest(
                symbol=tick.symbol,
                market=tick.market,
                exchange=tick.exchange,
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                price=price,
                volume=self.volume,
                strategy_id=self.strategy_id,
            )
        )
        self._ordered_symbols.add(key)
