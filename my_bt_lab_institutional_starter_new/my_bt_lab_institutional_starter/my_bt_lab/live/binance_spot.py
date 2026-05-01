from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from .gateway_base import MarketDataGateway
from .models import Market, Tick


class BinanceSpotGateway(MarketDataGateway):
    """Free Binance spot BBO stream gateway.

    Uses a public combined websocket endpoint and emits normalized Tick objects.
    This gateway does not require an API key.
    """

    def __init__(
        self,
        symbols: list[str],
        reconnect_delay: float = 3.0,
        base_url: str = "wss://data-stream.binance.vision/stream?streams=",
        open_timeout: float = 10.0,
    ) -> None:
        self.symbols = [s.lower() for s in symbols]
        self.reconnect_delay = reconnect_delay
        self.base_url = base_url
        self.open_timeout = open_timeout
        self._ws: Any = None
        self._stopped = False

    async def connect(self) -> None:
        self._stopped = False

    async def subscribe(self, symbols: list[str]) -> None:
        self.symbols = [s.lower() for s in symbols]

    async def ticks(self) -> AsyncIterator[Tick]:
        import websockets

        await self.connect()
        while not self._stopped:
            if not self.symbols:
                await asyncio.sleep(self.reconnect_delay)
                continue

            streams = "/".join(f"{symbol}@bookTicker" for symbol in self.symbols)
            url = f"{self.base_url}{streams}"
            print(f"[BinanceSpotGateway] connecting: {url}", flush=True)

            try:
                async with websockets.connect(
                    url,
                    open_timeout=self.open_timeout,
                    ping_interval=20,
                    ping_timeout=60,
                    close_timeout=5,
                ) as ws:
                    self._ws = ws
                    print("[BinanceSpotGateway] connected", flush=True)
                    async for message in ws:
                        raw = json.loads(message)
                        data = raw.get("data", raw)
                        tick = self._to_tick(data)
                        if tick is not None:
                            yield tick
            except Exception as exc:
                print(f"[BinanceSpotGateway] reconnect after error: {type(exc).__name__}: {exc}", flush=True)
                await asyncio.sleep(self.reconnect_delay)

    async def close(self) -> None:
        self._stopped = True
        if self._ws is not None:
            await self._ws.close()

    @staticmethod
    def _to_tick(data: dict[str, Any]) -> Tick | None:
        symbol = data.get("s")
        if not symbol:
            return None

        return Tick(
            symbol=str(symbol),
            market=Market.CRYPTO,
            exchange="BINANCE",
            ts_event=None,
            ts_recv=datetime.now(timezone.utc),
            bid_price=_to_float(data.get("b")),
            bid_volume=_to_float(data.get("B")),
            ask_price=_to_float(data.get("a")),
            ask_volume=_to_float(data.get("A")),
            source="BINANCE_SPOT_BOOK_TICKER",
            is_realtime=True,
            is_delayed=False,
        )


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, "", "--"):
            return None
        return float(value)
    except Exception:
        return None
