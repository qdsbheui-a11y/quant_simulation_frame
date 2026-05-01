from __future__ import annotations

import uuid
from collections.abc import Iterable

from .models import Fill, Order, OrderRequest, OrderStatus, OrderType, Side, Tick


class SimpleMatchingEngine:
    """Naive paper-trading matcher.

    Assumptions:
    - Market buy fills at ask; market sell fills at bid.
    - Limit buy fills when limit >= ask.
    - Limit sell fills when limit <= bid.
    - Full fill only; no queue position or partial fill model yet.
    """

    def __init__(self) -> None:
        self.active_orders: dict[str, Order] = {}

    def submit(self, request: OrderRequest) -> Order:
        order = Order(order_id=str(uuid.uuid4()), request=request)
        self.active_orders[order.order_id] = order
        return order

    def cancel(self, order_id: str) -> Order | None:
        order = self.active_orders.pop(order_id, None)
        if order is not None:
            order.status = OrderStatus.CANCELLED
        return order

    def on_tick(self, tick: Tick) -> list[Fill]:
        fills: list[Fill] = []
        for order_id, order in list(self.active_orders.items()):
            if not _same_instrument(order, tick):
                continue

            fill_price = _get_fill_price(order, tick)
            if fill_price is None:
                continue

            remaining = order.request.volume - order.traded
            if remaining <= 0:
                continue

            fill = Fill(
                order_id=order.order_id,
                symbol=order.request.symbol,
                market=order.request.market,
                exchange=order.request.exchange,
                side=order.request.side,
                price=fill_price,
                volume=remaining,
                ts=tick.ts_event or tick.ts_recv,
            )
            fills.append(fill)

            order.traded += remaining
            order.avg_price = fill_price
            order.status = OrderStatus.FILLED
            self.active_orders.pop(order_id, None)

        return fills

    def open_orders(self) -> Iterable[Order]:
        return self.active_orders.values()


def _same_instrument(order: Order, tick: Tick) -> bool:
    return (
        order.request.symbol == tick.symbol
        and order.request.market == tick.market
        and order.request.exchange == tick.exchange
    )


def _get_fill_price(order: Order, tick: Tick) -> float | None:
    req = order.request

    if req.order_type == OrderType.MARKET:
        if req.side == Side.BUY:
            return tick.ask_price or tick.last_price
        return tick.bid_price or tick.last_price

    if req.order_type == OrderType.LIMIT:
        if req.price is None:
            return None
        if req.side == Side.BUY and tick.ask_price is not None and req.price >= tick.ask_price:
            return tick.ask_price
        if req.side == Side.SELL and tick.bid_price is not None and req.price <= tick.bid_price:
            return tick.bid_price

        # Snapshot-only feeds may not have BBO. Fall back to last price for coarse simulation.
        if tick.last_price is not None:
            if req.side == Side.BUY and req.price >= tick.last_price:
                return tick.last_price
            if req.side == Side.SELL and req.price <= tick.last_price:
                return tick.last_price

    return None
