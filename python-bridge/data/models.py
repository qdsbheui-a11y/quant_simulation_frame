from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class TickData:
    """Canonical tick payload shared by backtest and live/simulation runtimes."""

    vt_symbol: str
    symbol: str
    exchange: str
    datetime: datetime
    last_price: float
    bid_price_1: float
    bid_volume_1: float
    ask_price_1: float
    ask_volume_1: float
    volume: float = 0.0
    open_interest: float = 0.0
    source: str = "unknown"


@dataclass(slots=True)
class BarData:
    """Canonical OHLCV bar payload shared by strategy code and adapters."""

    vt_symbol: str
    symbol: str
    exchange: str
    datetime: datetime
    interval: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float = 0.0
    open_interest: float = 0.0
    source: str = "unknown"
