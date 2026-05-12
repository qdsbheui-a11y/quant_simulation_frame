from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from simulation.models import Tick


@dataclass(slots=True)
class TickData:
    """Framework-level normalized tick model.

    Realtime ticks and historical ticks should both be converted to this model
    before being delivered to strategies, runtimes, or execution modules.
    """

    vt_symbol: str
    symbol: str
    exchange: str
    datetime: datetime
    last_price: float
    volume: float = 0.0
    open_interest: float = 0.0
    bid_price: float | None = None
    ask_price: float | None = None
    bid_volume: float | None = None
    ask_volume: float | None = None
    source: str = "unknown"

    @classmethod
    def from_simulation_tick(cls, tick: Tick) -> "TickData":
        return cls(
            vt_symbol=tick.vt_symbol,
            symbol=tick.symbol,
            exchange=tick.exchange,
            datetime=tick.datetime,
            last_price=tick.last_price,
            volume=tick.volume,
            open_interest=tick.open_interest,
            bid_price=tick.bid_price_1,
            ask_price=tick.ask_price_1,
            bid_volume=tick.bid_volume_1,
            ask_volume=tick.ask_volume_1,
            source=tick.source,
        )

    def to_simulation_tick(self) -> Tick:
        return Tick(
            vt_symbol=self.vt_symbol,
            symbol=self.symbol,
            exchange=self.exchange,
            datetime=self.datetime,
            last_price=self.last_price,
            bid_price_1=self.bid_price or 0.0,
            bid_volume_1=self.bid_volume or 0.0,
            ask_price_1=self.ask_price or 0.0,
            ask_volume_1=self.ask_volume or 0.0,
            volume=self.volume,
            open_interest=self.open_interest,
            source=self.source,
        )


@dataclass(slots=True)
class BarData:
    """Framework-level normalized bar model."""

    vt_symbol: str
    symbol: str
    exchange: str
    datetime: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    open_interest: float = 0.0
    source: str = "unknown"
