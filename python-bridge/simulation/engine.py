from __future__ import annotations

from datetime import datetime
from typing import Callable
from uuid import uuid4

from .models import (
    AccountState,
    Direction,
    Offset,
    Order,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    SimulationConfig,
    Tick,
    Trade,
)


OrderCallback = Callable[[Order], None]
TradeCallback = Callable[[Trade], None]
AccountCallback = Callable[[AccountState], None]
PositionCallback = Callable[[Position], None]


class SimulationEngine:
    """Minimal paper-trading simulation engine.

    The engine is intentionally deterministic and local. It consumes ticks,
    stores active orders, matches executable orders, and updates account and
    position state. It does not depend on vn.py or SimNow.
    """

    def __init__(self, config: SimulationConfig | None = None) -> None:
        self.config = config or SimulationConfig()
        self.account = AccountState(
            balance=self.config.initial_balance,
            available=self.config.initial_balance,
        )
        self.positions: dict[str, Position] = {}
        self.orders: dict[str, Order] = {}
        self.active_order_ids: set[str] = set()
        self.trades: dict[str, Trade] = {}
        self.last_ticks: dict[str, Tick] = {}

        self.order_callbacks: list[OrderCallback] = []
        self.trade_callbacks: list[TradeCallback] = []
        self.account_callbacks: list[AccountCallback] = []
        self.position_callbacks: list[PositionCallback] = []

    def on_order(self, callback: OrderCallback) -> None:
        self.order_callbacks.append(callback)

    def on_trade(self, callback: TradeCallback) -> None:
        self.trade_callbacks.append(callback)

    def on_account(self, callback: AccountCallback) -> None:
        self.account_callbacks.append(callback)

    def on_position(self, callback: PositionCallback) -> None:
        self.position_callbacks.append(callback)

    def submit_order(self, request: OrderRequest) -> Order:
        order = Order.from_request(request)

        rejection_reason = self._validate_order(order)
        if rejection_reason:
            order.status = OrderStatus.REJECTED
            order.updated_at = datetime.now()
            self.orders[order.order_id] = order
            self._emit_order(order)
            return order

        order.status = OrderStatus.NOT_TRADED
        order.updated_at = datetime.now()
        self.orders[order.order_id] = order
        self.active_order_ids.add(order.order_id)
        self._emit_order(order)

        tick = self.last_ticks.get(order.vt_symbol)
        if tick:
            self._try_match_order(order, tick)

        return order

    def cancel_order(self, order_id: str) -> Order | None:
        order = self.orders.get(order_id)
        if not order:
            return None
        if order.status in {OrderStatus.ALL_TRADED, OrderStatus.CANCELLED, OrderStatus.REJECTED}:
            return order

        order.status = OrderStatus.CANCELLED
        order.updated_at = datetime.now()
        self.active_order_ids.discard(order_id)
        self._emit_order(order)
        return order

    def on_tick(self, tick: Tick) -> None:
        self.last_ticks[tick.vt_symbol] = tick
        self._recalculate_unrealized_pnl()

        active_ids = list(self.active_order_ids)
        for order_id in active_ids:
            order = self.orders.get(order_id)
            if order and order.vt_symbol == tick.vt_symbol:
                self._try_match_order(order, tick)

        self._emit_account()

    def snapshot(self) -> dict:
        return {
            "account": self.account,
            "positions": list(self.positions.values()),
            "orders": list(self.orders.values()),
            "activeOrderIds": sorted(self.active_order_ids),
            "trades": list(self.trades.values()),
            "lastTicks": list(self.last_ticks.values()),
        }

    def _validate_order(self, order: Order) -> str | None:
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

    def _try_match_order(self, order: Order, tick: Tick) -> None:
        if order.status not in {OrderStatus.NOT_TRADED, OrderStatus.PART_TRADED}:
            return

        match_price = self._get_match_price(order, tick)
        if match_price is None:
            return

        fill_volume = order.remaining
        if fill_volume <= 0:
            return

        trade = Trade(
            trade_id=str(uuid4()),
            order_id=order.order_id,
            vt_symbol=order.vt_symbol,
            direction=order.direction,
            offset=order.offset,
            price=match_price,
            volume=fill_volume,
            datetime=tick.datetime,
        )
        self.trades[trade.trade_id] = trade

        order.traded += fill_volume
        order.status = OrderStatus.ALL_TRADED if order.remaining <= 0 else OrderStatus.PART_TRADED
        order.updated_at = datetime.now()
        if order.status == OrderStatus.ALL_TRADED:
            self.active_order_ids.discard(order.order_id)

        self._apply_trade(trade)
        self._emit_trade(trade)
        self._emit_order(order)

    def _get_match_price(self, order: Order, tick: Tick) -> float | None:
        if order.order_type == OrderType.MARKET:
            if self.config.market_order_price_source == "last":
                base_price = tick.last_price
            elif order.direction == Direction.LONG:
                base_price = tick.ask_price_1 or tick.last_price
            else:
                base_price = tick.bid_price_1 or tick.last_price
            return self._apply_slippage(order.direction, base_price)

        if order.direction == Direction.LONG:
            executable = tick.ask_price_1 > 0 and order.price >= tick.ask_price_1
            base_price = tick.ask_price_1 or tick.last_price
        else:
            executable = tick.bid_price_1 > 0 and order.price <= tick.bid_price_1
            base_price = tick.bid_price_1 or tick.last_price

        if not executable:
            return None
        return self._apply_slippage(order.direction, base_price)

    def _apply_slippage(self, direction: Direction, price: float) -> float:
        if direction == Direction.LONG:
            return round(price + self.config.slippage, 8)
        return round(price - self.config.slippage, 8)

    def _apply_trade(self, trade: Trade) -> None:
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

        self._recalculate_unrealized_pnl()
        self._emit_position(position)
        self._emit_account()

    def _recalculate_unrealized_pnl(self) -> None:
        unrealized = 0.0
        for vt_symbol, position in self.positions.items():
            tick = self.last_ticks.get(vt_symbol)
            if not tick:
                continue
            price = tick.last_price
            unrealized += (price - position.long_avg_price) * position.long_volume
            unrealized += (position.short_avg_price - price) * position.short_volume
        self.account.unrealized_pnl = unrealized

    def _emit_order(self, order: Order) -> None:
        for callback in self.order_callbacks:
            callback(order)

    def _emit_trade(self, trade: Trade) -> None:
        for callback in self.trade_callbacks:
            callback(trade)

    def _emit_account(self) -> None:
        for callback in self.account_callbacks:
            callback(self.account)

    def _emit_position(self, position: Position) -> None:
        for callback in self.position_callbacks:
            callback(position)
