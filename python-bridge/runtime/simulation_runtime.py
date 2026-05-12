from __future__ import annotations

from typing import Any, Type

from data.models import TickData
from execution.simulation_execution import SimulationExecution
from simulation.engine import SimulationEngine
from strategy.base import BaseStrategy
from strategy.context import StrategyContext


class SimulationRuntime:
    """Realtime tick runtime for unified strategies.

    The runtime feeds normalized realtime ticks into a strategy and routes the
    strategy's order intents to the local simulation execution adapter.

    By default, each tick first matches already-active orders and then reaches
    the strategy. This avoids the optimistic assumption that an order generated
    after seeing the current tick can be filled by that same tick.
    """

    def __init__(
        self,
        strategy_cls: Type[BaseStrategy],
        strategy_id: str,
        simulation_engine: SimulationEngine,
        strategy_params: dict[str, Any] | None = None,
        match_before_strategy: bool = True,
    ) -> None:
        self.strategy_id = strategy_id
        self.execution = SimulationExecution(simulation_engine)
        self.ctx = StrategyContext(strategy_id=strategy_id, execution=self.execution)
        self.strategy = strategy_cls(self.ctx, **(strategy_params or {}))
        self.match_before_strategy = match_before_strategy
        self.started = False

    def start(self) -> None:
        if self.started:
            return
        self.started = True
        self.strategy.on_start()

    def stop(self) -> None:
        if not self.started:
            return
        self.strategy.on_stop()
        self.started = False

    def on_tick(self, tick: TickData) -> None:
        if not self.started:
            self.start()

        if self.match_before_strategy:
            self.execution.on_tick(tick)
            self.strategy.on_tick(tick)
        else:
            self.strategy.on_tick(tick)
            self.execution.on_tick(tick)

    def on_order(self, order: Any) -> None:
        self.strategy.on_order(order)

    def on_trade(self, trade: Any) -> None:
        self.strategy.on_trade(trade)

    def on_account(self, account: Any) -> None:
        self.strategy.on_account(account)

    def on_position(self, position: Any) -> None:
        self.strategy.on_position(position)
