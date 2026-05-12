from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Protocol

from data.models import TickData
from execution.models import OrderIntent
from strategy.base import BaseStrategy, StrategyContext


class ExecutionAdapter(Protocol):
    def on_tick(self, tick: TickData) -> None:
        """Receive market data before/after strategy processing."""

    def submit_order_intent(self, intent: OrderIntent) -> object:
        """Convert an OrderIntent into runtime-specific execution."""

    def snapshot(self) -> dict:
        """Return runtime-specific execution state."""


@dataclass(slots=True)
class RuntimeResult:
    ticks_processed: int = 0
    submitted_intents: list[OrderIntent] = field(default_factory=list)
    execution_snapshot: dict | None = None


class BaseRuntime:
    """Base class for runtimes that run the same strategy interface."""

    def __init__(self, strategy: BaseStrategy, execution: ExecutionAdapter) -> None:
        self.strategy = strategy
        self.execution = execution
        self.submitted_intents: list[OrderIntent] = []
        self.strategy.bind(StrategyContext(strategy.strategy_id, self.submit_order_intent))

    def submit_order_intent(self, intent: OrderIntent) -> object:
        if intent.strategy_id is None:
            intent.strategy_id = self.strategy.strategy_id
        self.submitted_intents.append(intent)
        return self.execution.submit_order_intent(intent)

    def run_ticks(self, ticks: Iterable[TickData]) -> RuntimeResult:
        ticks_processed = 0
        self.strategy.on_start()
        for tick in ticks:
            self.execution.on_tick(tick)
            for intent in self.strategy.on_tick(tick):
                self.submit_order_intent(intent)
            ticks_processed += 1
        self.strategy.on_stop()
        return RuntimeResult(
            ticks_processed=ticks_processed,
            submitted_intents=list(self.submitted_intents),
            execution_snapshot=self.execution.snapshot(),
        )
