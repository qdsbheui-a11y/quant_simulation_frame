from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

from .gateway_base import MarketDataGateway
from .models import Tick
from .recorder import tick_from_dict


class ReplayGateway(MarketDataGateway):
    """Replay normalized ticks from a JSONL file recorded by JsonlTickRecorder."""

    def __init__(self, path: str | Path, speed: float = 0.0) -> None:
        self.path = Path(path)
        self.speed = speed
        self.symbols: set[str] = set()
        self._stopped = False

    async def connect(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        self._stopped = False

    async def subscribe(self, symbols: list[str]) -> None:
        self.symbols = set(symbols)

    async def ticks(self) -> AsyncIterator[Tick]:
        await self.connect()
        with self.path.open("r", encoding="utf-8") as fp:
            for line in fp:
                if self._stopped:
                    return
                line = line.strip()
                if not line:
                    continue
                tick = tick_from_dict(json.loads(line))
                if self.symbols and tick.symbol not in self.symbols:
                    continue
                yield tick
                if self.speed > 0:
                    await asyncio.sleep(self.speed)

    async def close(self) -> None:
        self._stopped = True
