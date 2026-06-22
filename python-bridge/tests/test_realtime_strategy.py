from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from realtime import BuyAndHoldOnFirstTickStrategy, RealtimeStrategyRunner
from simulation.engine import SimulationEngine
from simulation.models import OrderType, SimulationConfig, Tick


def make_tick(vt_symbol: str = "BTCUSDT.BINANCE") -> Tick:
    symbol, exchange = vt_symbol.split(".", 1)
    return Tick(
        vt_symbol=vt_symbol,
        symbol=symbol,
        exchange=exchange,
        datetime=datetime(2026, 5, 10, 12, 0, 0),
        last_price=100.0,
        bid_price_1=99.9,
        bid_volume_1=10,
        ask_price_1=100.1,
        ask_volume_1=10,
        source="test",
    )


def test_buy_and_hold_strategy_submits_only_once_per_symbol() -> None:
    engine = SimulationEngine(SimulationConfig(commission_rate=0.0))
    engine.on_tick(make_tick())

    strategy = BuyAndHoldOnFirstTickStrategy(
        symbols={"BTCUSDT.BINANCE"},
        volume=2,
        order_type=OrderType.MARKET,
    )
    runner = RealtimeStrategyRunner(strategy=strategy, engine=engine)

    first_requests = runner.on_tick(make_tick())
    second_requests = runner.on_tick(make_tick())

    assert len(first_requests) == 1
    assert first_requests[0].vt_symbol == "BTCUSDT.BINANCE"
    assert first_requests[0].volume == 2
    assert first_requests[0].order_type == OrderType.MARKET
    assert second_requests == []
    assert runner.generated_orders == 1


def test_buy_and_hold_strategy_ignores_unconfigured_symbol() -> None:
    engine = SimulationEngine()
    strategy = BuyAndHoldOnFirstTickStrategy(symbols={"ETHUSDT.BINANCE"}, volume=1)
    runner = RealtimeStrategyRunner(strategy=strategy, engine=engine)

    assert runner.on_tick(make_tick("BTCUSDT.BINANCE")) == []
    assert runner.generated_orders == 0
