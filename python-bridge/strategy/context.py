from __future__ import annotations

from typing import Any

from .intent import OrderAction, OrderIntent


class StrategyContext:
    """Strategy-facing API shared by backtest and realtime simulation runtimes.

    Strategies should call this context instead of calling Backtrader, HTTP API,
    or SimulationEngine directly. The concrete execution adapter decides how to
    translate an OrderIntent into a real order request for the active runtime.
    """

    def __init__(self, strategy_id: str, execution: Any) -> None:
        self.strategy_id = strategy_id
        self.execution = execution

    def buy_open(
        self,
        vt_symbol: str,
        volume: float,
        price: float | None = None,
        order_type: str = "LIMIT",
        reason: str | None = None,
    ) -> Any:
        return self._send(OrderAction.BUY_OPEN, vt_symbol, volume, price, order_type, reason)

    def sell_close(
        self,
        vt_symbol: str,
        volume: float,
        price: float | None = None,
        order_type: str = "LIMIT",
        reason: str | None = None,
    ) -> Any:
        return self._send(OrderAction.SELL_CLOSE, vt_symbol, volume, price, order_type, reason)

    def sell_open(
        self,
        vt_symbol: str,
        volume: float,
        price: float | None = None,
        order_type: str = "LIMIT",
        reason: str | None = None,
    ) -> Any:
        return self._send(OrderAction.SELL_OPEN, vt_symbol, volume, price, order_type, reason)

    def buy_close(
        self,
        vt_symbol: str,
        volume: float,
        price: float | None = None,
        order_type: str = "LIMIT",
        reason: str | None = None,
    ) -> Any:
        return self._send(OrderAction.BUY_CLOSE, vt_symbol, volume, price, order_type, reason)

    def get_account(self) -> Any:
        return self.execution.get_account()

    def get_position(self, vt_symbol: str) -> Any:
        return self.execution.get_position(vt_symbol)

    def get_orders(self) -> Any:
        return self.execution.get_orders()

    def get_trades(self) -> Any:
        return self.execution.get_trades()

    def _send(
        self,
        action: OrderAction,
        vt_symbol: str,
        volume: float,
        price: float | None,
        order_type: str,
        reason: str | None,
    ) -> Any:
        if volume <= 0:
            raise ValueError("volume must be positive")

        intent = OrderIntent(
            strategy_id=self.strategy_id,
            vt_symbol=vt_symbol,
            action=action,
            volume=volume,
            price=price,
            order_type=order_type.upper(),
            reason=reason,
        )
        return self.execution.send_intent(intent)
