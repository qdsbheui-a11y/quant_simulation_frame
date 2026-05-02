from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import uuid4


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class Offset(str, Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"


class OrderType(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class OrderStatus(str, Enum):
    SUBMITTING = "SUBMITTING"
    NOT_TRADED = "NOT_TRADED"
    PART_TRADED = "PART_TRADED"
    ALL_TRADED = "ALL_TRADED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass(slots=True)
class Tick:
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
class OrderRequest:
    vt_symbol: str
    direction: Direction
    offset: Offset
    price: float
    volume: float
    order_type: OrderType = OrderType.LIMIT


@dataclass(slots=True)
class Order:
    order_id: str
    vt_symbol: str
    direction: Direction
    offset: Offset
    price: float
    volume: float
    traded: float = 0.0
    status: OrderStatus = OrderStatus.SUBMITTING
    order_type: OrderType = OrderType.LIMIT
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    @property
    def remaining(self) -> float:
        return max(0.0, self.volume - self.traded)

    @classmethod
    def from_request(cls, request: OrderRequest) -> "Order":
        return cls(
            order_id=str(uuid4()),
            vt_symbol=request.vt_symbol,
            direction=request.direction,
            offset=request.offset,
            price=request.price,
            volume=request.volume,
            order_type=request.order_type,
        )


@dataclass(slots=True)
class Trade:
    trade_id: str
    order_id: str
    vt_symbol: str
    direction: Direction
    offset: Offset
    price: float
    volume: float
    datetime: datetime = field(default_factory=datetime.now)


@dataclass(slots=True)
class Position:
    vt_symbol: str
    long_volume: float = 0.0
    short_volume: float = 0.0
    long_avg_price: float = 0.0
    short_avg_price: float = 0.0


@dataclass(slots=True)
class AccountState:
    balance: float
    available: float
    frozen: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    commission: float = 0.0


@dataclass(slots=True)
class SimulationConfig:
    initial_balance: float = 1_000_000.0
    commission_rate: float = 0.0001
    slippage: float = 0.0
    reject_short_without_position: bool = True
    market_order_price_source: Literal["last", "opposite"] = "opposite"
