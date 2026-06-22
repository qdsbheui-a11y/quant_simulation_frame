from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal


Side = Literal["BUY", "SELL"]
PriceField = Literal["open_price", "close_price"]
RebalanceFrequency = Literal["daily", "weekly", "monthly"]


@dataclass(slots=True)
class DailyBar:
    vt_symbol: str
    symbol: str
    exchange: str
    date: date
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float = 0.0
    turnover: float = 0.0
    float_market_cap: float | None = None
    total_market_cap: float | None = None
    is_st: bool = False
    is_suspended: bool = False
    listing_days: int | None = None
    limit_up: float | None = None
    limit_down: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def price(self, field_name: PriceField) -> float:
        if field_name == "open_price":
            return self.open_price
        if field_name == "close_price":
            return self.close_price
        raise ValueError(f"unsupported price field: {field_name}")

    @property
    def is_limit_up(self) -> bool:
        return self.limit_up is not None and self.close_price >= self.limit_up

    @property
    def is_limit_down(self) -> bool:
        return self.limit_down is not None and self.close_price <= self.limit_down


@dataclass(slots=True)
class TargetWeight:
    vt_symbol: str
    weight: float


@dataclass(slots=True)
class BacktestConfig:
    initial_cash: float = 1_000_000.0
    commission_rate: float = 0.0003
    min_commission: float = 5.0
    stamp_tax_rate: float = 0.0005
    slippage_bps: float = 0.0
    lot_size: int = 100
    cash_buffer: float = 0.03
    price_field: PriceField = "open_price"
    rebalance_frequency: RebalanceFrequency = "monthly"


@dataclass(slots=True)
class PositionState:
    vt_symbol: str
    volume: int = 0
    avg_price: float = 0.0

    def market_value(self, price: float) -> float:
        return self.volume * price


@dataclass(slots=True)
class BacktestTrade:
    date: date
    vt_symbol: str
    side: Side
    price: float
    volume: int
    amount: float
    commission: float
    tax: float
    cash_delta: float
    realized_pnl: float = 0.0
    reason: str = "rebalance"


@dataclass(slots=True)
class EquitySnapshot:
    date: date
    cash: float
    market_value: float
    total_equity: float
    commission: float
    tax: float
    turnover: float
    realized_pnl: float


@dataclass(slots=True)
class BacktestResult:
    equity_curve: list[EquitySnapshot]
    trades: list[BacktestTrade]
    final_positions: dict[str, PositionState]
    metrics: dict[str, float]
