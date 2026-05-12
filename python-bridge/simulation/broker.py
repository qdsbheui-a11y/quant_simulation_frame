from __future__ import annotations

from data.models import TickData
from execution.models import AccountState, Direction, Offset, Order, OrderType, Position, SimulationConfig, Trade


class Broker:
    """Owns account/position state and validates broker-side constraints."""

    def __init__(self, config: SimulationConfig | None = None) -> None:
        self.config = config or SimulationConfig()
        self.account = AccountState(
            balance=self.config.initial_balance,
            available=self.config.initial_balance,
        )
        self.positions: dict[str, Position] = {}

    def validate_order(self, order: Order) -> str | None:
        if order.volume <= 0:
            return "volume must be positive"
        if order.order_type == OrderType.LIMIT and order.price <= 0:
            return "limit price must be positive"

        if order.offset == Offset.CLOSE and self.config.reject_short_without_position:
            position = self.positions.get(order.vt_symbol)
            if order.direction == Direction.SHORT:
                available = position.long_volume if position else 0.0
            else:
                available = position.short_volume if position else 0.0
            if available < order.volume:
                return "not enough position to close"

        return None

    def apply_trade(self, trade: Trade, last_ticks: dict[str, TickData]) -> Position:
        commission = abs(trade.price * trade.volume * self.config.commission_rate)
        self.account.commission += commission
        self.account.balance -= commission
        self.account.available = self.account.balance

        position = self.positions.setdefault(trade.vt_symbol, Position(vt_symbol=trade.vt_symbol))

        if trade.offset == Offset.OPEN:
            if trade.direction == Direction.LONG:
                total_cost = position.long_avg_price * position.long_volume + trade.price * trade.volume
                position.long_volume += trade.volume
                position.long_avg_price = total_cost / position.long_volume
            else:
                total_cost = position.short_avg_price * position.short_volume + trade.price * trade.volume
                position.short_volume += trade.volume
                position.short_avg_price = total_cost / position.short_volume
        else:
            if trade.direction == Direction.SHORT:
                close_volume = min(trade.volume, position.long_volume)
                realized = (trade.price - position.long_avg_price) * close_volume
                position.long_volume -= close_volume
                if position.long_volume <= 0:
                    position.long_volume = 0.0
                    position.long_avg_price = 0.0
            else:
                close_volume = min(trade.volume, position.short_volume)
                realized = (position.short_avg_price - trade.price) * close_volume
                position.short_volume -= close_volume
                if position.short_volume <= 0:
                    position.short_volume = 0.0
                    position.short_avg_price = 0.0

            self.account.realized_pnl += realized
            self.account.balance += realized
            self.account.available = self.account.balance

        self.recalculate_unrealized_pnl(last_ticks)
        return position

    def recalculate_unrealized_pnl(self, last_ticks: dict[str, TickData]) -> None:
        unrealized = 0.0
        for vt_symbol, position in self.positions.items():
            tick = last_ticks.get(vt_symbol)
            if not tick:
                continue
            price = tick.last_price
            unrealized += (price - position.long_avg_price) * position.long_volume
            unrealized += (position.short_avg_price - price) * position.short_volume
        self.account.unrealized_pnl = unrealized
