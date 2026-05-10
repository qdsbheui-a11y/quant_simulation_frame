from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from .models import DailyBar, PositionState, TargetWeight


@dataclass(slots=True)
class BacktestContext:
    date: date
    cash: float
    total_equity: float
    positions: dict[str, PositionState]


class BacktestStrategy(Protocol):
    def generate_targets(self, context: BacktestContext, bars: list[DailyBar]) -> list[TargetWeight]:
        ...


class EqualWeightSmallCapStrategy:
    """Equal-weight small-cap stock selection strategy.

    It filters untradable bars, sorts by market capitalization ascending, and
    assigns equal target weights to the smallest N symbols.
    """

    def __init__(
        self,
        top_n: int = 30,
        min_listing_days: int = 60,
        min_turnover: float = 20_000_000.0,
        market_cap_field: str = "float_market_cap",
        exclude_limit_up: bool = True,
        exclude_limit_down: bool = True,
    ) -> None:
        if top_n <= 0:
            raise ValueError("top_n must be positive")
        self.top_n = top_n
        self.min_listing_days = min_listing_days
        self.min_turnover = min_turnover
        self.market_cap_field = market_cap_field
        self.exclude_limit_up = exclude_limit_up
        self.exclude_limit_down = exclude_limit_down

    def generate_targets(self, context: BacktestContext, bars: list[DailyBar]) -> list[TargetWeight]:
        candidates = [bar for bar in bars if self._is_candidate(bar)]
        candidates.sort(key=self._market_cap)
        selected = candidates[: self.top_n]
        if not selected:
            return []

        weight = 1.0 / len(selected)
        return [TargetWeight(vt_symbol=bar.vt_symbol, weight=weight) for bar in selected]

    def _is_candidate(self, bar: DailyBar) -> bool:
        if bar.is_st or bar.is_suspended:
            return False
        if bar.open_price <= 0 or bar.close_price <= 0:
            return False
        if bar.listing_days is not None and bar.listing_days < self.min_listing_days:
            return False
        if bar.turnover < self.min_turnover:
            return False
        if self.exclude_limit_up and bar.is_limit_up:
            return False
        if self.exclude_limit_down and bar.is_limit_down:
            return False
        return self._market_cap(bar) > 0

    def _market_cap(self, bar: DailyBar) -> float:
        value = getattr(bar, self.market_cap_field, None)
        if value is None:
            return float("inf")
        return float(value)
