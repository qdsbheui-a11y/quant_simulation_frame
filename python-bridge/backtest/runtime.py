from __future__ import annotations

from dataclasses import dataclass, field

from data.models import TickData
from execution.models import OrderIntent, OrderRequest
from runtime.base import BaseRuntime
from strategy.base import BaseStrategy


@dataclass(slots=True)
class BacktestExecution:
    """Minimal backtest execution placeholder for a future Backtrader adapter."""

    ticks: list[TickData] = field(default_factory=list)
    order_requests: list[OrderRequest] = field(default_factory=list)

    def on_tick(self, tick: TickData) -> None:
        self.ticks.append(tick)

    def submit_order_intent(self, intent: OrderIntent) -> OrderRequest:
        request = OrderRequest.from_intent(intent)
        self.order_requests.append(request)
        return request

    def snapshot(self) -> dict:
        return {"ticks": list(self.ticks), "orderRequests": list(self.order_requests)}


class BacktestRuntime(BaseRuntime):
    """Runtime for historical ticks that reuses the same BaseStrategy contract."""

    def __init__(self, strategy: BaseStrategy, execution: BacktestExecution | None = None) -> None:
        super().__init__(strategy, execution or BacktestExecution())
