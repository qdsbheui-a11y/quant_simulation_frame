from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simulation.engine import SimulationEngine
from simulation.models import Direction, Offset, OrderRequest, OrderStatus, OrderType, SimulationConfig, Tick


def make_tick(
    vt_symbol: str = "au2606.SHFE",
    last: float = 560.0,
    bid: float = 559.9,
    ask: float = 560.1,
) -> Tick:
    symbol, exchange = vt_symbol.split(".", 1)
    return Tick(
        vt_symbol=vt_symbol,
        symbol=symbol,
        exchange=exchange,
        datetime=datetime(2026, 5, 5, 9, 0, 0),
        last_price=last,
        bid_price_1=bid,
        bid_volume_1=10,
        ask_price_1=ask,
        ask_volume_1=10,
        volume=100,
        open_interest=10000,
        source="test",
    )


def test_limit_long_open_matches_against_ask_price() -> None:
    engine = SimulationEngine(SimulationConfig(initial_balance=1_000_000, commission_rate=0.0001))
    engine.on_tick(make_tick())

    order = engine.submit_order(
        OrderRequest(
            vt_symbol="au2606.SHFE",
            direction=Direction.LONG,
            offset=Offset.OPEN,
            price=560.1,
            volume=2,
            order_type=OrderType.LIMIT,
        )
    )

    assert order.status == OrderStatus.ALL_TRADED
    assert order.traded == 2
    assert len(engine.trades) == 1

    trade = next(iter(engine.trades.values()))
    assert trade.price == 560.1
    assert trade.volume == 2

    position = engine.positions["au2606.SHFE"]
    assert position.long_volume == 2
    assert position.long_avg_price == 560.1
    assert engine.account.commission == 560.1 * 2 * 0.0001


def test_non_executable_limit_order_can_be_cancelled() -> None:
    engine = SimulationEngine()
    engine.on_tick(make_tick())

    order = engine.submit_order(
        OrderRequest(
            vt_symbol="au2606.SHFE",
            direction=Direction.LONG,
            offset=Offset.OPEN,
            price=559.0,
            volume=1,
            order_type=OrderType.LIMIT,
        )
    )

    assert order.status == OrderStatus.NOT_TRADED
    assert order.order_id in engine.active_order_ids

    cancelled = engine.cancel_order(order.order_id)
    assert cancelled is not None
    assert cancelled.status == OrderStatus.CANCELLED
    assert order.order_id not in engine.active_order_ids


def test_close_without_position_is_rejected() -> None:
    engine = SimulationEngine()

    order = engine.submit_order(
        OrderRequest(
            vt_symbol="au2606.SHFE",
            direction=Direction.SHORT,
            offset=Offset.CLOSE,
            price=560.0,
            volume=1,
            order_type=OrderType.LIMIT,
        )
    )

    assert order.status == OrderStatus.REJECTED
    assert order.order_id not in engine.active_order_ids
    assert not engine.trades


def test_open_then_close_long_updates_realized_pnl() -> None:
    engine = SimulationEngine(SimulationConfig(initial_balance=1_000_000, commission_rate=0.0))
    engine.on_tick(make_tick(last=560.0, bid=559.9, ask=560.0))

    open_order = engine.submit_order(
        OrderRequest(
            vt_symbol="au2606.SHFE",
            direction=Direction.LONG,
            offset=Offset.OPEN,
            price=560.0,
            volume=3,
            order_type=OrderType.LIMIT,
        )
    )
    assert open_order.status == OrderStatus.ALL_TRADED

    engine.on_tick(make_tick(last=563.0, bid=563.0, ask=563.1))
    close_order = engine.submit_order(
        OrderRequest(
            vt_symbol="au2606.SHFE",
            direction=Direction.SHORT,
            offset=Offset.CLOSE,
            price=563.0,
            volume=3,
            order_type=OrderType.LIMIT,
        )
    )

    assert close_order.status == OrderStatus.ALL_TRADED
    assert engine.positions["au2606.SHFE"].long_volume == 0
    assert engine.account.realized_pnl == 9.0
    assert engine.account.balance == 1_000_009.0


def test_market_order_uses_opposite_price_by_default() -> None:
    engine = SimulationEngine(SimulationConfig(slippage=0.2))
    engine.on_tick(make_tick(last=560.0, bid=559.8, ask=560.2))

    order = engine.submit_order(
        OrderRequest(
            vt_symbol="au2606.SHFE",
            direction=Direction.LONG,
            offset=Offset.OPEN,
            price=1.0,
            volume=1,
            order_type=OrderType.MARKET,
        )
    )

    assert order.status == OrderStatus.ALL_TRADED
    trade = next(iter(engine.trades.values()))
    assert trade.price == 560.4
