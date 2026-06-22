from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.models import DailyBar, PositionState
from paper import SmallCapPaperConfig, build_smallcap_rebalance_plan
from simulation.models import Direction, Offset, OrderType


def bar(vt_symbol: str, price: float, market_cap: float) -> DailyBar:
    symbol, exchange = vt_symbol.split(".", 1)
    return DailyBar(
        vt_symbol=vt_symbol,
        symbol=symbol,
        exchange=exchange,
        date=date(2024, 1, 2),
        open_price=price,
        high_price=price,
        low_price=price,
        close_price=price,
        turnover=100_000_000,
        float_market_cap=market_cap,
        listing_days=200,
    )


def test_smallcap_paper_plan_generates_buy_orders_for_selected_symbols() -> None:
    bars = [
        bar("000001.SZ", 10, 300),
        bar("000002.SZ", 20, 100),
        bar("000003.SZ", 30, 200),
    ]

    plan = build_smallcap_rebalance_plan(
        trading_date=date(2024, 1, 2),
        bars=bars,
        positions={},
        config=SmallCapPaperConfig(
            top_n=2,
            account_value=100_000,
            cash_buffer=0.0,
            min_turnover=0,
            order_type=OrderType.MARKET,
        ),
    )

    assert plan.selected_symbols == ["000002.SZ", "000003.SZ"]
    assert plan.sell_orders == []
    assert len(plan.buy_orders) == 2
    assert all(order.direction == Direction.LONG for order in plan.buy_orders)
    assert all(order.offset == Offset.OPEN for order in plan.buy_orders)
    assert {order.vt_symbol for order in plan.buy_orders} == {"000002.SZ", "000003.SZ"}


def test_smallcap_paper_plan_sells_removed_position_first() -> None:
    bars = [
        bar("000001.SZ", 10, 300),
        bar("000002.SZ", 20, 100),
    ]
    positions = {
        "000001.SZ": PositionState(vt_symbol="000001.SZ", volume=1000, avg_price=10),
    }

    plan = build_smallcap_rebalance_plan(
        trading_date=date(2024, 1, 2),
        bars=bars,
        positions=positions,
        config=SmallCapPaperConfig(
            top_n=1,
            account_value=100_000,
            cash_buffer=0.0,
            min_turnover=0,
            order_type=OrderType.MARKET,
        ),
    )

    assert plan.selected_symbols == ["000002.SZ"]
    assert len(plan.sell_orders) == 1
    assert plan.sell_orders[0].vt_symbol == "000001.SZ"
    assert plan.sell_orders[0].direction == Direction.SHORT
    assert plan.sell_orders[0].offset == Offset.CLOSE
    assert plan.orders[0] == plan.sell_orders[0]
