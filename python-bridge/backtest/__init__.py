"""Daily backtesting package for the local simulation framework."""

from .data import CsvDailyBarDataSource, DailyBarDataSource, InMemoryDailyBarDataSource
from .models import BacktestConfig, BacktestResult, BacktestTrade, DailyBar, EquitySnapshot, PositionState, TargetWeight
from .runner import BacktestRunner
from .strategy import BacktestContext, BacktestStrategy, EqualWeightSmallCapStrategy

__all__ = [
    "BacktestConfig",
    "BacktestContext",
    "BacktestResult",
    "BacktestRunner",
    "BacktestStrategy",
    "BacktestTrade",
    "CsvDailyBarDataSource",
    "DailyBar",
    "DailyBarDataSource",
    "EqualWeightSmallCapStrategy",
    "EquitySnapshot",
    "InMemoryDailyBarDataSource",
    "PositionState",
    "TargetWeight",
]
