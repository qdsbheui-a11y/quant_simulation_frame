from __future__ import annotations

from datetime import datetime
from typing import Callable
from uuid import uuid4

from data.models import TickData
from execution.models import AccountState, Order, OrderRequest, OrderStatus, Position, Trade

from .broker import Broker
from .matcher import Matcher

OrderCallback = Callable[[Order], None]
TradeCallback = Callable[[Trade], None]
AccountCallback = Callable[[AccountState], None]
PositionCallback = Callable[[Position], None]


class Exchange:
    """Order book facade: accepts requests, routes to matcher, emits trades."""

    def __init__(self, broker: Broker, matcher: Matcher) -> None:
        self.broker = broker
        self.matcher = matcher
        self.orders: dict[str, Order] = {}
        self.active_order_ids: set[str] = set()
        self.trades: dict[str, Trade] = {}
        self.last_ticks: dict[str, TickData] = {}
        self.order_callbacks: list[OrderCallback] = []
        self.trade_callbacks: list[TradeCallback] = []
        self.account_callbacks: list[AccountCallback] = []
        self.position_callbacks: list[PositionCallback] = []

    def submit_order(self, request: OrderRequest) -> Order:
        order = Order.from_request(request)

        rejection_reason = self.broker.validate_order(order)
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

    def on_tick(self, tick: TickData) -> None:
        self.last_ticks[tick.vt_symbol] = tick
        self.broker.recalculate_unrealized_pnl(self.last_ticks)

        active_ids = list(self.active_order_ids)
        for order_id in active_ids:
            order = self.orders.get(order_id)
            if order and order.vt_symbol == tick.vt_symbol:
                self._try_match_order(order, tick)

        self._emit_account()

    def _try_match_order(self, order: Order, tick: TickData) -> None:
        if order.status not in {OrderStatus.NOT_TRADED, OrderStatus.PART_TRADED}:
            return

        match_price = self.matcher.get_match_price(order, tick)
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
            strategy_id=order.strategy_id,
            datetime=tick.datetime,
        )
        self.trades[trade.trade_id] = trade

        order.traded += fill_volume
        order.status = OrderStatus.ALL_TRADED if order.remaining <= 0 else OrderStatus.PART_TRADED
        order.updated_at = datetime.now()
        if order.status == OrderStatus.ALL_TRADED:
            self.active_order_ids.discard(order.order_id)

        position = self.broker.apply_trade(trade, self.last_ticks)
        self._emit_trade(trade)
        self._emit_order(order)
        self._emit_position(position)
        self._emit_account()

    def _emit_order(self, order: Order) -> None:
        for callback in self.order_callbacks:
            callback(order)

    def _emit_trade(self, trade: Trade) -> None:
        for callback in self.trade_callbacks:
            callback(trade)

    def _emit_account(self) -> None:
        for callback in self.account_callbacks:
            callback(self.broker.account)

    def _emit_position(self, position: Position) -> None:
        for callback in self.position_callbacks:
            callback(position)
