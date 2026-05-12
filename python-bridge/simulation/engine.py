from __future__ import annotations

from data.models import TickData
from execution.models import AccountState, Order, OrderRequest, Position, SimulationConfig, Trade

from .broker import Broker
from .exchange import AccountCallback, Exchange, OrderCallback, PositionCallback, TradeCallback
from .matcher import Matcher


class SimulationEngine:
    """Facade for the realtime paper-trading chain.

    Flow: TickData -> strategy/runtime -> OrderIntent -> OrderRequest ->
    SimulationEngine -> Broker -> Exchange -> Matcher -> Trade.
    """

    def __init__(self, config: SimulationConfig | None = None) -> None:
        self.config = config or SimulationConfig()
        self.broker = Broker(self.config)
        self.matcher = Matcher(self.config)
        self.exchange = Exchange(self.broker, self.matcher)

    @property
    def account(self) -> AccountState:
        return self.broker.account

    @property
    def positions(self) -> dict[str, Position]:
        return self.broker.positions

    @property
    def orders(self) -> dict[str, Order]:
        return self.exchange.orders

    @property
    def active_order_ids(self) -> set[str]:
        return self.exchange.active_order_ids

    @property
    def trades(self) -> dict[str, Trade]:
        return self.exchange.trades

    @property
    def last_ticks(self) -> dict[str, TickData]:
        return self.exchange.last_ticks

    def on_order(self, callback: OrderCallback) -> None:
        self.exchange.order_callbacks.append(callback)

    def on_trade(self, callback: TradeCallback) -> None:
        self.exchange.trade_callbacks.append(callback)

    def on_account(self, callback: AccountCallback) -> None:
        self.exchange.account_callbacks.append(callback)

    def on_position(self, callback: PositionCallback) -> None:
        self.exchange.position_callbacks.append(callback)

    def submit_order(self, request: OrderRequest) -> Order:
        return self.exchange.submit_order(request)

    def cancel_order(self, order_id: str) -> Order | None:
        return self.exchange.cancel_order(order_id)

    def on_tick(self, tick: TickData) -> None:
        self.exchange.on_tick(tick)

    def snapshot(self) -> dict:
        return {
            "account": self.account,
            "positions": list(self.positions.values()),
            "orders": list(self.orders.values()),
            "activeOrderIds": sorted(self.active_order_ids),
            "trades": list(self.trades.values()),
            "lastTicks": list(self.last_ticks.values()),
        }
