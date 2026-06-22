from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Iterable, Protocol

from .models import DailyBar


class DailyBarDataSource(Protocol):
    def dates(self) -> list[date]:
        ...

    def bars_for_date(self, trading_date: date) -> list[DailyBar]:
        ...


class InMemoryDailyBarDataSource:
    def __init__(self, bars: Iterable[DailyBar]) -> None:
        grouped: dict[date, list[DailyBar]] = defaultdict(list)
        for bar in bars:
            grouped[bar.date].append(bar)
        self._bars_by_date = {key: value for key, value in grouped.items()}

    def dates(self) -> list[date]:
        return sorted(self._bars_by_date)

    def bars_for_date(self, trading_date: date) -> list[DailyBar]:
        return list(self._bars_by_date.get(trading_date, []))


class CsvDailyBarDataSource:
    """Load daily bars from one CSV file or a directory of CSV files.

    Required columns:
        date, vt_symbol, open_price, high_price, low_price, close_price

    Optional columns:
        symbol, exchange, volume, turnover, float_market_cap,
        total_market_cap, is_st, is_suspended, listing_days, limit_up, limit_down
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._bars_by_date: dict[date, list[DailyBar]] | None = None

    def dates(self) -> list[date]:
        self._ensure_loaded()
        assert self._bars_by_date is not None
        return sorted(self._bars_by_date)

    def bars_for_date(self, trading_date: date) -> list[DailyBar]:
        self._ensure_loaded()
        assert self._bars_by_date is not None
        return list(self._bars_by_date.get(trading_date, []))

    def _ensure_loaded(self) -> None:
        if self._bars_by_date is not None:
            return

        files: list[Path]
        if self.path.is_dir():
            files = sorted(self.path.glob("*.csv"))
        else:
            files = [self.path]

        grouped: dict[date, list[DailyBar]] = defaultdict(list)
        for file_path in files:
            with file_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
                reader = csv.DictReader(csv_file)
                for row in reader:
                    bar = _bar_from_row(row)
                    grouped[bar.date].append(bar)

        self._bars_by_date = {key: value for key, value in grouped.items()}


def _bar_from_row(row: dict[str, str]) -> DailyBar:
    vt_symbol = row["vt_symbol"].strip()
    symbol = row.get("symbol", "").strip()
    exchange = row.get("exchange", "").strip()
    if not symbol or not exchange:
        if "." in vt_symbol:
            symbol_part, exchange_part = vt_symbol.split(".", 1)
            symbol = symbol or symbol_part
            exchange = exchange or exchange_part
        else:
            symbol = symbol or vt_symbol

    return DailyBar(
        vt_symbol=vt_symbol,
        symbol=symbol,
        exchange=exchange,
        date=date.fromisoformat(row["date"].strip()),
        open_price=_float(row.get("open_price")),
        high_price=_float(row.get("high_price")),
        low_price=_float(row.get("low_price")),
        close_price=_float(row.get("close_price")),
        volume=_float(row.get("volume"), 0.0),
        turnover=_float(row.get("turnover"), 0.0),
        float_market_cap=_optional_float(row.get("float_market_cap")),
        total_market_cap=_optional_float(row.get("total_market_cap")),
        is_st=_bool(row.get("is_st")),
        is_suspended=_bool(row.get("is_suspended")),
        listing_days=_optional_int(row.get("listing_days")),
        limit_up=_optional_float(row.get("limit_up")),
        limit_down=_optional_float(row.get("limit_down")),
        extra={key: value for key, value in row.items() if key not in _KNOWN_COLUMNS},
    )


def _float(value: str | None, default: float | None = None) -> float:
    if value is None or value == "":
        if default is None:
            raise ValueError("missing required float value")
        return default
    return float(value)


def _optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    return int(float(value))


def _bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "t", "yes", "y"}


_KNOWN_COLUMNS = {
    "date",
    "vt_symbol",
    "symbol",
    "exchange",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
    "turnover",
    "float_market_cap",
    "total_market_cap",
    "is_st",
    "is_suspended",
    "listing_days",
    "limit_up",
    "limit_down",
}
