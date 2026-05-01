from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class Market(str, Enum):
    CRYPTO = "CRYPTO"
    CN_FUTURES = "CN_FUTURES"
    CN_STOCK = "CN_STOCK"
    CME = "CME"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class Tick:
    symbol: str
    market: Market
    exchange: str
    ts_event: Optional[datetime]
    ts_recv: datetime
    last_price: Optional[float] = None
    last_volume: Optional[float] = None
    bid_price: Optional[float] = None
    bid_volume: Optional[float] = None
    ask_price: Optional[float] = None
    ask_volume: Optional[float] = None
    source: str = ""
    is_realtime: bool = True
    is_delayed: bool = False
    delay_seconds: Optional[int] = None


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    market: Market
    exchange: str
    side: Side
    order_type: OrderType
    volume: float
    strategy_id: str
    price: Optional[float] = None


@dataclass
class Order:
    order_id: str
    request: OrderRequest
    status: OrderStatus = OrderStatus.NEW
    traded: float = 0.0
    avg_price: Optional[float] = None
    message: str = ""


@dataclass(frozen=True)
class Fill:
    order_id: str
    symbol: str
    market: Market
    exchange: str
    side: Side
    price: float
    volume: float
    ts: datetime
    commission: float = 0.0
