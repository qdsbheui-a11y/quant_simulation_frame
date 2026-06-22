from __future__ import annotations

from datetime import date

from .data import DailyBarDataSource
from .metrics import calculate_metrics
from .models import (
    BacktestConfig,
    BacktestResult,
    BacktestTrade,
    DailyBar,
    EquitySnapshot,
    PositionState,
    TargetWeight,
)
from .strategy import BacktestContext, BacktestStrategy


class BacktestRunner:
    def __init__(
        self,
        data_source: DailyBarDataSource,
        strategy: BacktestStrategy,
        config: BacktestConfig | None = None,
    ) -> None:
        self.data_source = data_source
        self.strategy = strategy
        self.config = config or BacktestConfig()

        self.cash = self.config.initial_cash
        self.positions: dict[str, PositionState] = {}
        self.trades: list[BacktestTrade] = []
        self.equity_curve: list[EquitySnapshot] = []
        self.total_commission = 0.0
        self.total_tax = 0.0
        self.total_realized_pnl = 0.0

    def run(self, start_date: date | None = None, end_date: date | None = None) -> BacktestResult:
        dates = [item for item in self.data_source.dates() if _in_range(item, start_date, end_date)]
        previous_date: date | None = None

        for trading_date in dates:
            bars = self.data_source.bars_for_date(trading_date)
            if not bars:
                previous_date = trading_date
                continue

            price_map = {bar.vt_symbol: bar.price(self.config.price_field) for bar in bars}
            turnover = 0.0

            if self._should_rebalance(trading_date, previous_date):
                total_equity = self._calculate_total_equity(price_map)
                context = BacktestContext(
                    date=trading_date,
                    cash=self.cash,
                    total_equity=total_equity,
                    positions={
                        key: PositionState(value.vt_symbol, value.volume, value.avg_price)
                        for key, value in self.positions.items()
                    },
                )
                targets = self.strategy.generate_targets(context, bars)
                turnover = self._rebalance(trading_date, bars, targets, total_equity)

            self._record_equity(trading_date, price_map, turnover)
            previous_date = trading_date

        metrics = calculate_metrics(self.equity_curve)
        final_positions = {key: value for key, value in self.positions.items() if value.volume > 0}
        return BacktestResult(
            equity_curve=self.equity_curve,
            trades=self.trades,
            final_positions=final_positions,
            metrics=metrics,
        )

    def _should_rebalance(self, trading_date: date, previous_date: date | None) -> bool:
        if previous_date is None:
            return True
        frequency = self.config.rebalance_frequency
        if frequency == "daily":
            return True
        if frequency == "weekly":
            return trading_date.isocalendar().week != previous_date.isocalendar().week
        if frequency == "monthly":
            return trading_date.month != previous_date.month or trading_date.year != previous_date.year
        raise ValueError(f"unsupported rebalance_frequency: {frequency}")

    def _rebalance(
        self,
        trading_date: date,
        bars: list[DailyBar],
        targets: list[TargetWeight],
        total_equity: float,
    ) -> float:
        bar_map = {bar.vt_symbol: bar for bar in bars}
        price_map = {bar.vt_symbol: bar.price(self.config.price_field) for bar in bars}
        target_weights = {item.vt_symbol: max(0.0, item.weight) for item in targets}
        total_weight = sum(target_weights.values())
        if total_weight > 1.0:
            target_weights = {key: value / total_weight for key, value in target_weights.items()}

        investable_equity = total_equity * (1 - self.config.cash_buffer)
        target_values = {key: investable_equity * value for key, value in target_weights.items()}
        turnover = 0.0

        # Sell first so cash is available for buys.
        symbols = set(self.positions) | set(target_values)
        for vt_symbol in sorted(symbols):
            position = self.positions.get(vt_symbol)
            if not position or position.volume <= 0:
                continue
            price = price_map.get(vt_symbol)
            bar = bar_map.get(vt_symbol)
            if price is None or price <= 0 or bar is None:
                continue
            if bar.is_suspended or bar.is_limit_down:
                continue
            current_value = position.volume * price
            target_value = target_values.get(vt_symbol, 0.0)
            diff_value = target_value - current_value
            if diff_value < 0:
                volume = _floor_to_lot(int(abs(diff_value) / price), self.config.lot_size)
                volume = min(volume, position.volume)
                if volume > 0:
                    turnover += self._execute_sell(trading_date, vt_symbol, price, volume)

        for vt_symbol in sorted(target_values):
            price = price_map.get(vt_symbol)
            bar = bar_map.get(vt_symbol)
            if price is None or price <= 0 or bar is None:
                continue
            if bar.is_suspended or bar.is_limit_up:
                continue
            position = self.positions.get(vt_symbol, PositionState(vt_symbol=vt_symbol))
            current_value = position.volume * price
            target_value = target_values[vt_symbol]
            diff_value = target_value - current_value
            if diff_value <= 0:
                continue

            volume = _floor_to_lot(int(diff_value / price), self.config.lot_size)
            while volume > 0:
                execution_price = self._apply_slippage(price, "BUY")
                amount = execution_price * volume
                commission = self._commission(amount)
                needed_cash = amount + commission
                if needed_cash <= self.cash:
                    break
                volume -= self.config.lot_size
            if volume > 0:
                turnover += self._execute_buy(trading_date, vt_symbol, price, volume)

        return turnover

    def _execute_buy(self, trading_date: date, vt_symbol: str, price: float, volume: int) -> float:
        execution_price = self._apply_slippage(price, "BUY")
        amount = execution_price * volume
        commission = self._commission(amount)
        cash_delta = -(amount + commission)
        self.cash += cash_delta
        self.total_commission += commission

        position = self.positions.setdefault(vt_symbol, PositionState(vt_symbol=vt_symbol))
        old_cost = position.avg_price * position.volume
        position.volume += volume
        position.avg_price = (old_cost + amount) / position.volume

        self.trades.append(
            BacktestTrade(
                date=trading_date,
                vt_symbol=vt_symbol,
                side="BUY",
                price=execution_price,
                volume=volume,
                amount=amount,
                commission=commission,
                tax=0.0,
                cash_delta=cash_delta,
            )
        )
        return amount

    def _execute_sell(self, trading_date: date, vt_symbol: str, price: float, volume: int) -> float:
        execution_price = self._apply_slippage(price, "SELL")
        amount = execution_price * volume
        commission = self._commission(amount)
        tax = amount * self.config.stamp_tax_rate

        position = self.positions[vt_symbol]
        realized_pnl = (execution_price - position.avg_price) * volume
        position.volume -= volume
        if position.volume <= 0:
            position.volume = 0
            position.avg_price = 0.0

        cash_delta = amount - commission - tax
        self.cash += cash_delta
        self.total_commission += commission
        self.total_tax += tax
        self.total_realized_pnl += realized_pnl

        self.trades.append(
            BacktestTrade(
                date=trading_date,
                vt_symbol=vt_symbol,
                side="SELL",
                price=execution_price,
                volume=volume,
                amount=amount,
                commission=commission,
                tax=tax,
                cash_delta=cash_delta,
                realized_pnl=realized_pnl,
            )
        )
        return amount

    def _record_equity(self, trading_date: date, price_map: dict[str, float], turnover: float) -> None:
        market_value = self._calculate_market_value(price_map)
        self.equity_curve.append(
            EquitySnapshot(
                date=trading_date,
                cash=self.cash,
                market_value=market_value,
                total_equity=self.cash + market_value,
                commission=self.total_commission,
                tax=self.total_tax,
                turnover=turnover,
                realized_pnl=self.total_realized_pnl,
            )
        )

    def _calculate_market_value(self, price_map: dict[str, float]) -> float:
        total = 0.0
        for vt_symbol, position in self.positions.items():
            if position.volume <= 0:
                continue
            price = price_map.get(vt_symbol)
            if price is not None:
                total += position.volume * price
        return total

    def _calculate_total_equity(self, price_map: dict[str, float]) -> float:
        return self.cash + self._calculate_market_value(price_map)

    def _commission(self, amount: float) -> float:
        if amount <= 0:
            return 0.0
        return max(amount * self.config.commission_rate, self.config.min_commission)

    def _apply_slippage(self, price: float, side: str) -> float:
        slippage = price * self.config.slippage_bps / 10_000
        if side == "BUY":
            return price + slippage
        return max(0.0, price - slippage)


def _floor_to_lot(volume: int, lot_size: int) -> int:
    if lot_size <= 1:
        return max(0, volume)
    return max(0, volume // lot_size * lot_size)


def _in_range(value: date, start_date: date | None, end_date: date | None) -> bool:
    if start_date is not None and value < start_date:
        return False
    if end_date is not None and value > end_date:
        return False
    return True
