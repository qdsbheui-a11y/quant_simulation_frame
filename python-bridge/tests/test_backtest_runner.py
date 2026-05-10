from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest import BacktestConfig, BacktestRunner, DailyBar, EqualWeightSmallCapStrategy, InMemoryDailyBarDataSource


def bar(
    trading_date: date,
    vt_symbol: str,
    close_price: float,
    market_cap: float,
    turnover: float = 100_000_000.0,
) -> DailyBar:
    symbol, exchange = vt_symbol.split(".", 1)
    return DailyBar(
        vt_symbol=vt_symbol,
        symbol=symbol,
        exchange=exchange,
        date=trading_date,
        open_price=close_price,
        high_price=close_price,
        low_price=close_price,
        close_price=close_price,
        turnover=turnover,
        float_market_cap=market_cap,
        listing_days=200,
    )


def test_small_cap_strategy_selects_lowest_market_cap() -> None:
    strategy = EqualWeightSmallCapStrategy(top_n=2, min_turnover=0)
    bars = [
        bar(date(2024, 1, 2), "000001.SZ", 10, 300),
        bar(date(2024, 1, 2), "000002.SZ", 10, 100),
        bar(date(2024, 1, 2), "000003.SZ", 10, 200),
    ]

    targets = strategy.generate_targets(
        context=None,  # type: ignore[arg-type]
        bars=bars,
    )

    assert [item.vt_symbol for item in targets] == ["000002.SZ", "000003.SZ"]
    assert targets[0].weight == 0.5


def test_backtest_runner_rebalances_and_records_equity() -> None:
    bars = [
        bar(date(2024, 1, 2), "000001.SZ", 10, 100),
        bar(date(2024, 1, 2), "000002.SZ", 20, 200),
        bar(date(2024, 1, 3), "000001.SZ", 11, 100),
        bar(date(2024, 1, 3), "000002.SZ", 19, 200),
    ]
    data_source = InMemoryDailyBarDataSource(bars)
    runner = BacktestRunner(
        data_source=data_source,
        strategy=EqualWeightSmallCapStrategy(top_n=1, min_turnover=0),
        config=BacktestConfig(
            initial_cash=100_000,
            commission_rate=0.0,
            min_commission=0.0,
            stamp_tax_rate=0.0,
            cash_buffer=0.0,
            rebalance_frequency="daily",
            price_field="close_price",
        ),
    )

    result = runner.run()

    assert len(result.equity_curve) == 2
    assert result.final_positions["000001.SZ"].volume == 10_000
    assert result.equity_curve[-1].total_equity == 110_000
    assert result.metrics["total_return"] == 0.1


def test_runner_sells_removed_symbol_before_buying_new_symbol() -> None:
    bars = [
        bar(date(2024, 1, 2), "000001.SZ", 10, 100),
        bar(date(2024, 1, 2), "000002.SZ", 10, 200),
        bar(date(2024, 2, 1), "000001.SZ", 10, 300),
        bar(date(2024, 2, 1), "000002.SZ", 10, 50),
    ]
    runner = BacktestRunner(
        data_source=InMemoryDailyBarDataSource(bars),
        strategy=EqualWeightSmallCapStrategy(top_n=1, min_turnover=0),
        config=BacktestConfig(
            initial_cash=100_000,
            commission_rate=0.0,
            min_commission=0.0,
            stamp_tax_rate=0.0,
            cash_buffer=0.0,
            rebalance_frequency="monthly",
            price_field="close_price",
        ),
    )

    result = runner.run()

    assert [trade.side for trade in result.trades] == ["BUY", "SELL", "BUY"]
    assert "000001.SZ" not in result.final_positions
    assert result.final_positions["000002.SZ"].volume == 10_000
    assert result.equity_curve[-1].total_equity == 100_000
