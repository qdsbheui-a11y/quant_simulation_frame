from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from simulation.engine import SimulationEngine
from simulation.models import AccountState, Order, OrderRequest, Position, Tick, Trade

from .base import BaseStrategy


class StrategyEngine:
    """Routes market and simulation events between strategies and SimulationEngine."""

    def __init__(self, simulation: SimulationEngine) -> None:
        self.simulation = simulation
        self.strategies: dict[str, BaseStrategy] = {}
        self.logs: list[dict[str, Any]] = []

    def add_strategy(self, strategy: BaseStrategy) -> None:
        if strategy.name in self.strategies:
            raise ValueError(f"Strategy already exists: {strategy.name}")
        self.strategies[strategy.name] = strategy
        strategy.on_init()
        self.write_log(strategy.name, "initialized")

    def remove_strategy(self, name: str) -> None:
        strategy = self.strategies.pop(name, None)
        if strategy and strategy.active:
            strategy.on_stop()
        if strategy:
            self.write_log(name, "removed")

    def start_strategy(self, name: str) -> None:
        strategy = self._get_strategy(name)
        if not strategy.active:
            strategy.on_start()
            self.write_log(name, "started")

    def stop_strategy(self, name: str) -> None:
        strategy = self._get_strategy(name)
        if strategy.active:
            strategy.on_stop()
            self.write_log(name, "stopped")

    def on_tick(self, tick: Tick) -> None:
        for strategy in list(self.strategies.values()):
            if strategy.active:
                strategy.on_tick(tick)

    def on_order(self, order: Order) -> None:
        for strategy in list(self.strategies.values()):
            strategy.on_order(order)

    def on_trade(self, trade: Trade) -> None:
        for strategy in list(self.strategies.values()):
            strategy.on_trade(trade)

    def on_account(self, account: AccountState) -> None:
        for strategy in list(self.strategies.values()):
            strategy.on_account(account)

    def on_position(self, position: Position) -> None:
        for strategy in list(self.strategies.values()):
            strategy.on_position(position)

    def send_order(self, request: OrderRequest) -> Order:
        return self.simulation.submit_order(request)

    def write_log(self, strategy_name: str, message: str) -> None:
        self.logs.append(
            {
                "datetime": datetime.now().isoformat(timespec="seconds"),
                "strategy": strategy_name,
                "message": message,
            }
        )
        self.logs = self.logs[-500:]

    def snapshot(self) -> dict[str, Any]:
        return {
            "strategies": [self._to_jsonable(strategy.snapshot()) for strategy in self.strategies.values()],
            "logs": self.logs[-100:],
        }

    def _get_strategy(self, name: str) -> BaseStrategy:
        strategy = self.strategies.get(name)
        if not strategy:
            raise KeyError(f"Strategy not found: {name}")
        return strategy

    def _to_jsonable(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, datetime):
            return value.isoformat()
        if is_dataclass(value):
            return {key: self._to_jsonable(val) for key, val in asdict(value).items()}
        if isinstance(value, dict):
            return {str(key): self._to_jsonable(val) for key, val in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._to_jsonable(item) for item in value]
        return value
