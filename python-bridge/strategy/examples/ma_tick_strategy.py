from __future__ import annotations

from data.models import TickData
from strategy.base import BaseStrategy


class MaTickStrategy(BaseStrategy):
    """Minimal moving-average strategy using the unified strategy API."""

    def __init__(self, ctx, fast: int = 5, slow: int = 20, volume: float = 1.0) -> None:
        super().__init__(ctx)
        if fast <= 0 or slow <= 0:
            raise ValueError("fast and slow must be positive")
        if fast >= slow:
            raise ValueError("fast should be smaller than slow")

        self.fast = fast
        self.slow = slow
        self.volume = volume
        self.prices: list[float] = []

    def on_tick(self, tick: TickData) -> None:
        self.prices.append(tick.last_price)
        if len(self.prices) < self.slow:
            return

        fast_ma = sum(self.prices[-self.fast :]) / self.fast
        slow_ma = sum(self.prices[-self.slow :]) / self.slow

        position = self.ctx.get_position(tick.vt_symbol)
        long_volume = getattr(position, "long_volume", 0.0) if position else 0.0

        if fast_ma > slow_ma and long_volume <= 0:
            self.ctx.buy_open(
                vt_symbol=tick.vt_symbol,
                volume=self.volume,
                price=tick.last_price,
                reason="fast_ma_above_slow_ma",
            )
        elif fast_ma < slow_ma and long_volume > 0:
            self.ctx.sell_close(
                vt_symbol=tick.vt_symbol,
                volume=min(self.volume, long_volume),
                price=tick.last_price,
                reason="fast_ma_below_slow_ma",
            )
