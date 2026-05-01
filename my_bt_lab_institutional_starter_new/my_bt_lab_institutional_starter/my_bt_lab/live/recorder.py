from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import Market, Tick


class JsonlTickRecorder:
    """Append normalized Tick records to a JSONL file.

    JSONL is deliberately used for the first version because it is simple,
    append-friendly, easy to inspect, and does not require extra dependencies.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = None

    def __enter__(self) -> "JsonlTickRecorder":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def open(self) -> None:
        if self._fp is None:
            self._fp = self.path.open("a", encoding="utf-8")

    def close(self) -> None:
        if self._fp is not None:
            self._fp.close()
            self._fp = None

    def write(self, tick: Tick) -> None:
        if self._fp is None:
            self.open()
        assert self._fp is not None
        self._fp.write(json.dumps(tick_to_dict(tick), ensure_ascii=False) + "\n")
        self._fp.flush()


def tick_to_dict(tick: Tick) -> dict[str, Any]:
    data = asdict(tick)
    data["market"] = tick.market.value
    data["ts_event"] = _dt_to_str(tick.ts_event)
    data["ts_recv"] = _dt_to_str(tick.ts_recv)
    return data


def tick_from_dict(data: dict[str, Any]) -> Tick:
    return Tick(
        symbol=str(data["symbol"]),
        market=Market(str(data["market"])),
        exchange=str(data["exchange"]),
        ts_event=_str_to_dt(data.get("ts_event")),
        ts_recv=_str_to_dt(data["ts_recv"]),
        last_price=_optional_float(data.get("last_price")),
        last_volume=_optional_float(data.get("last_volume")),
        bid_price=_optional_float(data.get("bid_price")),
        bid_volume=_optional_float(data.get("bid_volume")),
        ask_price=_optional_float(data.get("ask_price")),
        ask_volume=_optional_float(data.get("ask_volume")),
        source=str(data.get("source") or "REPLAY"),
        is_realtime=bool(data.get("is_realtime", False)),
        is_delayed=bool(data.get("is_delayed", False)),
        delay_seconds=data.get("delay_seconds"),
    )


def _dt_to_str(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _str_to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _optional_float(value: Any) -> float | None:
    if value in (None, "", "--"):
        return None
    return float(value)
