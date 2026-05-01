from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .gateway_base import MarketDataGateway
from .models import Market, Tick


class TushareRealtimeGateway(MarketDataGateway):
    """Tushare A-share realtime snapshot polling gateway.

    This is a polling gateway, not a websocket stream. It is intended for paper trading,
    watchlists, and low-frequency simulation. Requires TUSHARE_TOKEN or an explicit token.
    """

    def __init__(
        self,
        symbols: list[str],
        interval: float = 3.0,
        token: str | None = None,
        src: str = "sn",
        chunk_size: int = 50,
    ) -> None:
        self.symbols = symbols
        self.interval = interval
        self.token = token or os.getenv("TUSHARE_TOKEN")
        self.src = src
        self.chunk_size = chunk_size
        self.tz = ZoneInfo("Asia/Shanghai")
        self._stopped = False

    async def connect(self) -> None:
        if not self.token:
            raise RuntimeError("TUSHARE_TOKEN is not set")
        import tushare as ts

        ts.set_token(self.token)
        self._stopped = False

    async def subscribe(self, symbols: list[str]) -> None:
        self.symbols = symbols

    async def ticks(self) -> AsyncIterator[Tick]:
        await self.connect()
        while not self._stopped:
            try:
                for group in _chunks(self.symbols, self.chunk_size):
                    df = await asyncio.to_thread(self._fetch_realtime_quote, group)
                    if df is None or df.empty:
                        continue
                    for _, row in df.iterrows():
                        tick = self._row_to_tick(row)
                        if tick is not None:
                            yield tick
            except Exception as exc:
                print(f"[TushareRealtimeGateway] error: {exc}")

            await asyncio.sleep(self.interval)

    async def close(self) -> None:
        self._stopped = True

    def _fetch_realtime_quote(self, symbols: list[str]):
        import tushare as ts

        return ts.realtime_quote(ts_code=",".join(symbols), src=self.src)

    def _row_to_tick(self, row: Any) -> Tick | None:
        ts_code = _get(row, "TS_CODE", "ts_code", "代码", "股票代码")
        if not ts_code:
            return None

        date_str = _get(row, "DATE", "date")
        time_str = _get(row, "TIME", "time")
        ts_event = self._parse_cn_datetime(str(date_str), str(time_str)) if date_str and time_str else None

        return Tick(
            symbol=str(ts_code),
            market=Market.CN_STOCK,
            exchange=_infer_cn_stock_exchange(str(ts_code)),
            ts_event=ts_event,
            ts_recv=datetime.now(self.tz),
            last_price=_to_float(_get(row, "PRICE", "price", "最新价")),
            last_volume=_to_float(_get(row, "VOLUME", "volume", "成交量")),
            bid_price=_to_float(_get(row, "B1_P", "b1_p", "买一价")),
            bid_volume=_to_float(_get(row, "B1_V", "b1_v", "买一量")),
            ask_price=_to_float(_get(row, "A1_P", "a1_p", "卖一价")),
            ask_volume=_to_float(_get(row, "A1_V", "a1_v", "卖一量")),
            source=f"TUSHARE_REALTIME_QUOTE:{self.src}",
            is_realtime=False,
            is_delayed=False,
        )

    def _parse_cn_datetime(self, date_str: str, time_str: str) -> datetime | None:
        try:
            raw = f"{date_str} {time_str}"
            if "-" in date_str:
                return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=self.tz)
            return datetime.strptime(raw, "%Y%m%d %H:%M:%S").replace(tzinfo=self.tz)
        except Exception:
            return None


def _infer_cn_stock_exchange(ts_code: str) -> str:
    if ts_code.endswith(".SH"):
        return "SSE"
    if ts_code.endswith(".SZ"):
        return "SZSE"
    if ts_code.endswith(".BJ"):
        return "BSE"
    return "CN_STOCK"


def _chunks(items: list[str], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


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
