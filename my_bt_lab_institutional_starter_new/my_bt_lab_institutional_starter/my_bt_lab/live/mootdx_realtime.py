from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .gateway_base import MarketDataGateway
from .models import Market, Tick


class MootdxRealtimeGateway(MarketDataGateway):
    """A-share snapshot polling gateway backed by mootdx/TDX TCP quotes.

    This gateway uses TongDaXin-compatible quote servers through mootdx. It is a
    practical free fallback when Sina/Eastmoney HTTP sources used by Tushare,
    efinance, or AkShare are unstable in the local network environment.
    """

    def __init__(
        self,
        symbols: list[str],
        interval: float = 3.0,
        max_consecutive_errors: int = 10,
        max_backoff_seconds: float = 30.0,
    ) -> None:
        self.symbols = symbols
        self.interval = interval
        self.max_consecutive_errors = max_consecutive_errors
        self.max_backoff_seconds = max_backoff_seconds
        self.tz = ZoneInfo("Asia/Shanghai")
        self._client: Any = None
        self._stopped = False

    async def connect(self) -> None:
        from mootdx.quotes import Quotes

        # std market can cover standard A-share quote snapshots.
        self._client = Quotes.factory(market="std", multithread=True, heartbeat=True)
        self._stopped = False

    async def subscribe(self, symbols: list[str]) -> None:
        self.symbols = symbols

    async def ticks(self) -> AsyncIterator[Tick]:
        if self._client is None:
            await self.connect()

        consecutive_errors = 0
        while not self._stopped:
            emitted = 0
            try:
                df = await asyncio.to_thread(self._fetch_realtime_quote)
                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        tick = self._row_to_tick(row)
                        if tick is not None:
                            emitted += 1
                            yield tick

                consecutive_errors = 0
                if emitted == 0:
                    print(
                        f"[MootdxRealtimeGateway] empty response after filtering; symbols={self.symbols}",
                        flush=True,
                    )

            except Exception as exc:
                consecutive_errors += 1
                print(
                    f"[MootdxRealtimeGateway] error {consecutive_errors}/{self.max_consecutive_errors}: "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
                if consecutive_errors >= self.max_consecutive_errors:
                    raise RuntimeError("mootdx realtime polling failed repeatedly") from exc
                await asyncio.sleep(min(self.interval * consecutive_errors, self.max_backoff_seconds))
                continue

            await asyncio.sleep(self.interval)

    async def close(self) -> None:
        self._stopped = True
        self._client = None

    def _fetch_realtime_quote(self):
        assert self._client is not None
        codes = [_strip_ts_suffix(symbol).zfill(6) for symbol in self.symbols]
        return self._client.quotes(symbol=codes)

    def _row_to_tick(self, row: Any) -> Tick | None:
        code = _get(row, "code", "股票代码", "代码")
        if not code:
            return None

        market_value = _get(row, "market")
        symbol = _to_ts_code(str(code), market_value)
        last_price = _to_float(_get(row, "price", "最新价", "最新"))
        if last_price is None:
            return None

        return Tick(
            symbol=symbol,
            market=Market.CN_STOCK,
            exchange=_infer_cn_stock_exchange(symbol),
            ts_event=None,
            ts_recv=datetime.now(self.tz),
            last_price=last_price,
            last_volume=_to_float(_get(row, "volume", "成交量")),
            bid_price=_to_float(_get(row, "bid1", "buy1", "买一价")),
            bid_volume=_to_float(_get(row, "bid_vol1", "buy1_volume", "买一量")),
            ask_price=_to_float(_get(row, "ask1", "sell1", "卖一价")),
            ask_volume=_to_float(_get(row, "ask_vol1", "sell1_volume", "卖一量")),
            source="MOOTDX_TDX_QUOTES",
            is_realtime=False,
            is_delayed=False,
        )


def _strip_ts_suffix(symbol: str) -> str:
    return symbol.split(".", 1)[0]


def _to_ts_code(code: str, market_value: Any = None) -> str:
    value = _strip_ts_suffix(code).zfill(6)

    # mootdx/TDX convention: 0 = Shenzhen, 1 = Shanghai.
    try:
        market_int = int(market_value)
    except Exception:
        market_int = None

    if market_int == 1:
        return f"{value}.SH"
    if market_int == 0:
        return f"{value}.SZ"

    if value.startswith(("5", "6", "9")):
        return f"{value}.SH"
    if value.startswith(("0", "1", "2", "3")):
        return f"{value}.SZ"
    if value.startswith(("4", "8")):
        return f"{value}.BJ"
    return value


def _infer_cn_stock_exchange(ts_code: str) -> str:
    if ts_code.endswith(".SH"):
        return "SSE"
    if ts_code.endswith(".SZ"):
        return "SZSE"
    if ts_code.endswith(".BJ"):
        return "BSE"
    return "CN_STOCK"


def _get(row: Any, *names: str) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, "", "--"):
            return None
        return float(value)
    except Exception:
        return None
