from __future__ import annotations

from dataclasses import dataclass, field

from .matching import SimpleMatchingEngine
from .models import Fill, Market, Order, OrderRequest, OrderStatus, Side, Tick


@dataclass
class AccountSnapshot:
    cash: float
    positions: dict[str, float] = field(default_factory=dict)
    realized_pnl: float = 0.0


class SimBroker:
    """Local paper broker backed by SimpleMatchingEngine."""

    def __init__(self, initial_cash: float = 1_000_000.0) -> None:
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.positions: dict[str, float] = {}
        self.orders: dict[str, Order] = {}
        self.fills: list[Fill] = []
        self.matching = SimpleMatchingEngine()

    async def send_order(self, request: OrderRequest) -> Order:
        rejection = self._validate_request(request)
        if rejection:
            order = Order(
                order_id="REJECTED",
                request=request,
                status=OrderStatus.REJECTED,
                message=rejection,
            )
            return order

        order = self.matching.submit(request)
        self.orders[order.order_id] = order
        return order

    async def cancel_order(self, order_id: str) -> Order | None:
        order = self.matching.cancel(order_id)
        if order is not None:
            self.orders[order.order_id] = order
        return order

    def on_tick(self, tick: Tick) -> list[Fill]:
        fills = self.matching.on_tick(tick)
        for fill in fills:
            self._apply_fill(fill)
            self.fills.append(fill)
        return fills

    def snapshot(self) -> AccountSnapshot:
        return AccountSnapshot(cash=self.cash, positions=dict(self.positions))

    def _apply_fill(self, fill: Fill) -> None:
        amount = fill.price * fill.volume
        key = _position_key(fill.market, fill.exchange, fill.symbol)

        if fill.side == Side.BUY:
            self.cash -= amount + fill.commission
            self.positions[key] = self.positions.get(key, 0.0) + fill.volume
        else:
            self.cash += amount - fill.commission
            self.positions[key] = self.positions.get(key, 0.0) - fill.volume

    def _validate_request(self, request: OrderRequest) -> str:
        if request.volume <= 0:
            return "volume must be positive"
        if request.price is not None and request.price <= 0:
            return "price must be positive"
        if request.market == Market.CN_STOCK:
            if request.volume % 100 != 0:
                return "CN stock volume must be a multiple of 100 shares"
        return ""


def _position_key(market: Market, exchange: str, symbol: str) -> str:
    return f"{market.value}:{exchange}:{symbol}"
