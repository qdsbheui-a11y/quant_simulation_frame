"""Unified strategy API.

Strategies should depend on this package instead of depending directly on a
specific runtime such as Backtrader or the realtime simulation engine.
"""

from .base import BaseStrategy
from .context import StrategyContext
from .intent import OrderIntent, OrderAction

__all__ = ["BaseStrategy", "OrderAction", "OrderIntent", "StrategyContext"]
