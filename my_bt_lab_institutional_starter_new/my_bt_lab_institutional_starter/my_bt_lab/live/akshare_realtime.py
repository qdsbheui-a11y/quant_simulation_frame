from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .gateway_base import MarketDataGateway
from .models import Market, Tick


class AkShareRealtimeGateway(MarketDataGateway):
    """A-share snapshot polling gateway backed by AkShare.

    Uses ak.stock_zh_a_spot_em() to fetch an A-share market snapshot and then
    filters the requested symbols locally. This is a fallback for free A-share
    paper trading when Tushare/efinance realtime endpoints are unstable.
    """

    def __init__(
        self,
        symbols: list[str],
        interval: float = 5.0,
        max_consecutive_errors: int = 10,
        max_backoff_seconds: float = 30.0,
    ) -> None:
        self.symbols = symbols
        self.interval = interval
        self.max_consecutive_errors = max_consecutive_errors
        self.max_backoff_seconds = max_backoff_seconds
        self.tz = ZoneInfo("Asia/Shanghai")
        self._stopped = False

    async def connect(self) -> None:
        self._stopped = False

    async def subscribe(self, symbols: list[str]) -> None:
        self.symbols = symbols

    async def ticks(self) -> AsyncIterator[Tick]:
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
                        f"[AkShareRealtimeGateway] empty response after filtering; symbols={self.symbols}",
                        flush=True,
                    )

            except Exception as exc:
                consecutive_errors += 1
                print(
                    f"[AkShareRealtimeGateway] error {consecutive_errors}/{self.max_consecutive_errors}: "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
                if consecutive_errors >= self.max_consecutive_errors:
                    raise RuntimeError("AkShare realtime polling failed repeatedly") from exc
                await asyncio.sleep(min(self.interval * consecutive_errors, self.max_backoff_seconds))
                continue

            await asyncio.sleep(self.interval)

    async def close(self) -> None:
        self._stopped = True

    def _fetch_realtime_quote(self):
        import akshare as ak

        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty or not self.symbols:
            return df

        wanted = {_strip_ts_suffix(symbol).zfill(6) for symbol in self.symbols}
        code_column = _find_code_column(df.columns)
        if code_column is None:
            print(f"[AkShareRealtimeGateway] cannot find code column; columns={list(df.columns)}", flush=True)
            return df.iloc[0:0]

        codes = df[code_column].astype(str).map(lambda value: _strip_ts_suffix(value).zfill(6))
        return df[codes.isin(wanted)]

    def _row_to_tick(self, row: Any) -> Tick | None:
        code = _get(row, "代码", "股票代码", "code", "CODE")
        if not code:
            return None

        symbol = _to_ts_code(str(code))
        last_price = _to_float(_get(row, "最新价", "最新", "price", "PRICE"))
        if last_price is None:
            return None

        return Tick(
            symbol=symbol,
            market=Market.CN_STOCK,
            exchange=_infer_cn_stock_exchange(symbol),
            ts_event=None,
            ts_recv=datetime.now(self.tz),
            last_price=last_price,
            last_volume=_to_float(_get(row, "成交量", "volume", "VOLUME")),
            bid_price=None,
            bid_volume=None,
            ask_price=None,
            ask_volume=None,
            source="AKSHARE_STOCK_ZH_A_SPOT_EM",
            is_realtime=False,
            is_delayed=False,
        )


def _find_code_column(columns) -> str | None:
    for name in ("代码", "股票代码", "code", "CODE"):
        if name in columns:
            return name
    return None


def _strip_ts_suffix(symbol: str) -> str:
    return symbol.split(".", 1)[0]


def _to_ts_code(code: str) -> str:
    value = _strip_ts_suffix(code).zfill(6)
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
