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
class OrderIntent:
    """Runtime-independent order decision emitted by a strategy."""

    vt_symbol: str
    direction: Direction
    offset: Offset
    price: float
    volume: float
    order_type: OrderType = OrderType.LIMIT
    strategy_id: str | None = None
    reason: str | None = None

    def to_request(self) -> "OrderRequest":
        return OrderRequest(
            vt_symbol=self.vt_symbol,
            direction=self.direction,
            offset=self.offset,
            price=self.price,
            volume=self.volume,
            order_type=self.order_type,
            strategy_id=self.strategy_id,
        )


@dataclass(slots=True)
class OrderRequest:
    """Executable order request accepted by simulation/backtest executions."""

    vt_symbol: str
    direction: Direction
    offset: Offset
    price: float
    volume: float
    order_type: OrderType = OrderType.LIMIT
    strategy_id: str | None = None

    @classmethod
    def from_intent(cls, intent: OrderIntent) -> "OrderRequest":
        return cls(
            vt_symbol=intent.vt_symbol,
            direction=intent.direction,
            offset=intent.offset,
            price=intent.price,
            volume=intent.volume,
            order_type=intent.order_type,
            strategy_id=intent.strategy_id,
        )


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
    strategy_id: str | None = None
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
            strategy_id=request.strategy_id,
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
    strategy_id: str | None = None
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
