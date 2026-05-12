from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class OrderAction(str, Enum):
    """Strategy-level order intent actions.

    These actions keep strategy code independent from a concrete broker's
    direction/offset naming.
    """

    BUY_OPEN = "BUY_OPEN"
    SELL_CLOSE = "SELL_CLOSE"
    SELL_OPEN = "SELL_OPEN"
    BUY_CLOSE = "BUY_CLOSE"


@dataclass(slots=True)
class OrderIntent:
    """Order intent emitted by a strategy.

    Runtimes/execution adapters are responsible for converting this intent into
    a concrete order request for backtesting or realtime simulation.
    """

    strategy_id: str
    vt_symbol: str
    action: OrderAction
    volume: float
    price: float | None = None
    order_type: str = "LIMIT"
    reason: str | None = None
    datetime: datetime | None = None
