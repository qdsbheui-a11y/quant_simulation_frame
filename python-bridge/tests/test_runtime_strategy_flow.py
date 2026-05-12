from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest import BacktestRuntime
from data import TickData
from execution import OrderIntent, OrderStatus, OrderType
from runtime import SimulationRuntime
from strategy import BaseStrategy


def make_tick(
    vt_symbol: str = "au2606.SHFE",
    last: float = 560.0,
    bid: float = 559.9,
    ask: float = 560.1,
) -> TickData:
    symbol, exchange = vt_symbol.split(".", 1)
    return TickData(
        vt_symbol=vt_symbol,
        symbol=symbol,
        exchange=exchange,
        datetime=datetime(2026, 5, 5, 9, 0, 0),
        last_price=last,
        bid_price_1=bid,
        bid_volume_1=10,
        ask_price_1=ask,
        ask_volume_1=10,
    )


class BuyFirstTickStrategy(BaseStrategy):
    def __init__(self) -> None:
        super().__init__("buy_first_tick")
        self.seen = 0

    def on_tick(self, tick: TickData) -> list[OrderIntent]:
        self.seen += 1
        if self.seen == 1:
            return [self.buy(tick.vt_symbol, tick.ask_price_1, 1, OrderType.LIMIT)]
        return []


def test_same_strategy_runs_in_simulation_runtime() -> None:
    runtime = SimulationRuntime(BuyFirstTickStrategy())

    result = runtime.run_ticks([make_tick()])

    assert result.ticks_processed == 1
    assert len(result.submitted_intents) == 1
    order = result.execution_snapshot["orders"][0]
    assert order.status == OrderStatus.ALL_TRADED
    assert order.strategy_id == "buy_first_tick"


def test_same_strategy_runs_in_backtest_runtime() -> None:
    runtime = BacktestRuntime(BuyFirstTickStrategy())

    result = runtime.run_ticks([make_tick()])

    assert result.ticks_processed == 1
    assert len(result.submitted_intents) == 1
    request = result.execution_snapshot["orderRequests"][0]
    assert request.strategy_id == "buy_first_tick"
    assert request.vt_symbol == "au2606.SHFE"
