from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from .models import Tick


class MarketDataGateway(ABC):
    """Base interface for live, delayed, polling, and replay market data sources."""

    @abstractmethod
    async def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def subscribe(self, symbols: list[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def ticks(self) -> AsyncIterator[Tick]:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError
