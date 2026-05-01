from __future__ import annotations

from collections.abc import AsyncIterator

from .akshare_realtime import AkShareRealtimeGateway
from .efinance_realtime import EFinanceRealtimeGateway
from .gateway_base import MarketDataGateway
from .models import Tick
from .mootdx_realtime import MootdxRealtimeGateway
from .tushare_realtime import TushareRealtimeGateway


class AutoAShareGateway(MarketDataGateway):
    """A-share free snapshot gateway with ordered fallback.

    Priority:
    1. mootdx   - TDX TCP quote servers; preferred in this project
    2. tushare  - realtime_quote HTTP source
    3. efinance - public HTTP snapshot source
    4. akshare  - public HTTP snapshot source

    The fallback switches only if the current source raises. It does not merge
    multiple sources at the same time.
    """

    def __init__(
        self,
        symbols: list[str],
        interval: float = 3.0,
        max_consecutive_errors: int = 5,
        tushare_src: str = "sina",
    ) -> None:
        self.symbols = symbols
        self.interval = interval
        self.max_consecutive_errors = max_consecutive_errors
        self.tushare_src = tushare_src
        self._stopped = False
        self._current: MarketDataGateway | None = None

    async def connect(self) -> None:
        self._stopped = False

    async def subscribe(self, symbols: list[str]) -> None:
        self.symbols = symbols
        if self._current is not None:
            await self._current.subscribe(symbols)

    async def ticks(self) -> AsyncIterator[Tick]:
        await self.connect()

        for name, gateway in self._build_gateways():
            if self._stopped:
                return
            self._current = gateway
            print(f"[AutoAShareGateway] trying source={name}", flush=True)
            try:
                async for tick in gateway.ticks():
                    yield tick
                    if self._stopped:
                        await gateway.close()
                        return
            except Exception as exc:
                print(
                    f"[AutoAShareGateway] source={name} failed: {type(exc).__name__}: {exc}; trying next source",
                    flush=True,
                )
                try:
                    await gateway.close()
                except Exception:
                    pass
                continue

        raise RuntimeError("all A-share free realtime sources failed")

    async def close(self) -> None:
        self._stopped = True
        if self._current is not None:
            await self._current.close()

    def _build_gateways(self):
        yield "mootdx", MootdxRealtimeGateway(
            symbols=self.symbols,
            interval=self.interval,
            max_consecutive_errors=self.max_consecutive_errors,
        )
        yield "tushare", TushareRealtimeGateway(
            symbols=self.symbols,
            interval=self.interval,
            src=self.tushare_src,
            max_consecutive_errors=self.max_consecutive_errors,
        )
        yield "efinance", EFinanceRealtimeGateway(
            symbols=self.symbols,
            interval=self.interval,
            max_consecutive_errors=self.max_consecutive_errors,
        )
        yield "akshare", AkShareRealtimeGateway(
            symbols=self.symbols,
            interval=self.interval,
            max_consecutive_errors=self.max_consecutive_errors,
        )
