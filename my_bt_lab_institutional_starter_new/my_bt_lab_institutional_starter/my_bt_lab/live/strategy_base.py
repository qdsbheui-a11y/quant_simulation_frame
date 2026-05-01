from __future__ import annotations

from .models import Tick
from .sim_broker import SimBroker


class LiveStrategy:
    """Base class for paper/live event-driven strategies."""

    def __init__(self, strategy_id: str, broker: SimBroker) -> None:
        self.strategy_id = strategy_id
        self.broker = broker

    async def on_tick(self, tick: Tick) -> None:
        raise NotImplementedError
