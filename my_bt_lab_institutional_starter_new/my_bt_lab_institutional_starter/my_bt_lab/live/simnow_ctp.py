from __future__ import annotations

import asyncio
import json
import math
import queue
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .gateway_base import MarketDataGateway
from .models import Market, Tick


class SimNowCtpGateway(MarketDataGateway):
    """SimNow/CTP market data gateway using vnpy_ctp.api.MdApi.

    This gateway only receives market data and emits normalized Tick objects.
    It deliberately does not send real CTP orders. Paper orders should continue
    to go through SimBroker.
    """

    def __init__(
        self,
        config_path: str | Path = "my_bt_lab/live/config/simnow.local.json",
        symbols: list[str] | None = None,
    ) -> None:
        self.config_path = Path(config_path)
        self.symbols = symbols or []
        self.tz = ZoneInfo("Asia/Shanghai")
        self._queue: queue.Queue[Tick] = queue.Queue()
        self._client: _SimNowMdApi | None = None
        self._stopped = False

    async def connect(self) -> None:
        config = _load_config(self.config_path)
        symbols = self.symbols or list(config.get("instrument_ids") or [])
        if not symbols:
            raise RuntimeError("No CTP instrument_ids configured. Set --symbols or simnow.local.json instrument_ids.")

        self._stopped = False
        self._client = _SimNowMdApi(config=config, symbols=symbols, tick_queue=self._queue)
        self._client.connect()

    async def subscribe(self, symbols: list[str]) -> None:
        self.symbols = symbols
        if self._client is not None:
            self._client.subscribe(symbols)

    async def ticks(self) -> AsyncIterator[Tick]:
        if self._client is None:
            await self.connect()

        loop = asyncio.get_running_loop()
        while not self._stopped:
            tick = await loop.run_in_executor(None, self._queue.get)
            if tick is not None:
                yield tick

    async def close(self) -> None:
        self._stopped = True
        if self._client is not None:
            self._client.close()
            self._client = None


class _SimNowMdApi:
    """Thin callback adapter around vnpy_ctp.api.MdApi."""

    def __init__(self, config: dict[str, Any], symbols: list[str], tick_queue: queue.Queue[Tick]) -> None:
        from vnpy_ctp.api import MdApi

        class _Api(MdApi):
            pass

        self.api = _Api()
        self.config = config
        self.symbols = [_normalize_instrument_id(symbol) for symbol in symbols]
        self.tick_queue = tick_queue
        self.reqid = 0
        self.connected = False
        self.login_status = False
        self.tz = ZoneInfo("Asia/Shanghai")

        # Monkey-patch callbacks onto the pybind object. This matches vn.py's
        # callback naming convention while keeping the adapter self-contained.
        self.api.onFrontConnected = self.on_front_connected
        self.api.onFrontDisconnected = self.on_front_disconnected
        self.api.onRspUserLogin = self.on_rsp_user_login
        self.api.onRspError = self.on_rsp_error
        self.api.onRspSubMarketData = self.on_rsp_sub_market_data
        self.api.onRtnDepthMarketData = self.on_rtn_depth_market_data

    def connect(self) -> None:
        md_address = str(self.config["md_address"])
        flow_path = str(self.config.get("md_flow_path", "./runs/ctp_md_flow/"))
        Path(flow_path).mkdir(parents=True, exist_ok=True)

        print(f"[SimNowCtpGateway] connecting md={md_address}", flush=True)
        self._call("createFtdcMdApi", flow_path)
        self._call("registerFront", md_address)
        self._call("init")

    def subscribe(self, symbols: list[str]) -> None:
        self.symbols = [_normalize_instrument_id(symbol) for symbol in symbols]
        if self.login_status:
            self._subscribe_all()

    def close(self) -> None:
        try:
            self._call("close")
        except Exception:
            try:
                self._call("exit")
            except Exception:
                pass

    def on_front_connected(self) -> None:
        self.connected = True
        print("[SimNowCtpGateway] front connected; login", flush=True)
        self.reqid += 1
        req = {
            "BrokerID": str(self.config.get("broker_id", "9999")),
            "UserID": str(self.config["user_id"]),
            "Password": str(self.config["password"]),
        }
        self._call("reqUserLogin", req, self.reqid)

    def on_front_disconnected(self, reason: int) -> None:
        self.connected = False
        self.login_status = False
        print(f"[SimNowCtpGateway] front disconnected reason={reason}", flush=True)

    def on_rsp_user_login(self, data: Any, error: Any, reqid: int, last: bool) -> None:
        error_id = _error_id(error)
        if error_id:
            print(f"[SimNowCtpGateway] login failed error_id={error_id} error={error}", flush=True)
            return

        self.login_status = True
        print(f"[SimNowCtpGateway] login ok; subscribe={self.symbols}", flush=True)
        self._subscribe_all()

    def on_rsp_error(self, error: Any, reqid: int, last: bool) -> None:
        print(f"[SimNowCtpGateway] rsp error reqid={reqid} last={last} error={error}", flush=True)

    def on_rsp_sub_market_data(self, data: Any, error: Any, reqid: int, last: bool) -> None:
        error_id = _error_id(error)
        instrument = _get(data, "InstrumentID", "instrument_id")
        if error_id:
            print(f"[SimNowCtpGateway] subscribe failed instrument={instrument} error={error}", flush=True)
        else:
            print(f"[SimNowCtpGateway] subscribe ok instrument={instrument}", flush=True)

    def on_rtn_depth_market_data(self, data: Any) -> None:
        tick = _ctp_depth_to_tick(data, self.tz)
        if tick is not None:
            self.tick_queue.put(tick)

    def _subscribe_all(self) -> None:
        for symbol in self.symbols:
            print(f"[SimNowCtpGateway] subscribe {symbol}", flush=True)
            self._call("subscribeMarketData", symbol)

    def _call(self, name: str, *args):
        method = getattr(self.api, name, None)
        if method is None:
            # Some wrappers expose CTP methods with UpperCamelCase names.
            alt = name[:1].upper() + name[1:]
            method = getattr(self.api, alt, None)
        if method is None:
            raise AttributeError(f"vnpy_ctp MdApi does not expose method {name}")
        return method(*args)


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"SimNow config not found: {path}")
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def _normalize_instrument_id(symbol: str) -> str:
    return str(symbol).split(".", 1)[0]


def _ctp_depth_to_tick(data: Any, tz: ZoneInfo) -> Tick | None:
    instrument = _get(data, "InstrumentID", "instrument_id")
    if not instrument:
        return None

    exchange = str(_get(data, "ExchangeID", "exchange_id") or "SIMNOW")
    ts_event = _parse_ctp_datetime(data, tz)

    return Tick(
        symbol=str(instrument),
        market=Market.CN_FUTURES,
        exchange=exchange,
        ts_event=ts_event,
        ts_recv=datetime.now(tz),
        last_price=_valid_price(_get(data, "LastPrice", "last_price")),
        last_volume=_valid_price(_get(data, "Volume", "volume")),
        bid_price=_valid_price(_get(data, "BidPrice1", "bid_price_1", "bidPrice1")),
        bid_volume=_valid_price(_get(data, "BidVolume1", "bid_volume_1", "bidVolume1")),
        ask_price=_valid_price(_get(data, "AskPrice1", "ask_price_1", "askPrice1")),
        ask_volume=_valid_price(_get(data, "AskVolume1", "ask_volume_1", "askVolume1")),
        source="SIMNOW_CTP_MD",
        is_realtime=True,
        is_delayed=False,
    )


def _parse_ctp_datetime(data: Any, tz: ZoneInfo) -> datetime | None:
    action_day = _get(data, "ActionDay", "action_day") or _get(data, "TradingDay", "trading_day")
    update_time = _get(data, "UpdateTime", "update_time")
    update_ms = _get(data, "UpdateMillisec", "update_millisec") or 0
    if not action_day or not update_time:
        return None

    try:
        raw = f"{action_day} {update_time}.{int(update_ms):03d}"
        return datetime.strptime(raw, "%Y%m%d %H:%M:%S.%f").replace(tzinfo=tz)
    except Exception:
        return None


def _get(obj: Any, *names: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        for name in names:
            if name in obj:
                return obj[name]
        return None
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return None


def _error_id(error: Any) -> int:
    value = _get(error, "ErrorID", "error_id")
    try:
        return int(value or 0)
    except Exception:
        return 0


def _valid_price(value: Any) -> float | None:
    try:
        if value in (None, "", "--"):
            return None
        out = float(value)
        if math.isnan(out) or math.isinf(out) or abs(out) > 1e20:
            return None
        return out
    except Exception:
        return None
