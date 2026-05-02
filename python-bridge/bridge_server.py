"""Python bridge service for the simulation framework.

Current scope:
- exposes health/config endpoints;
- optionally connects to SimNow through vn.py CTP gateway;
- broadcasts ticks to WebSocket clients as JSON;
- provides a local mock tick source so the simulation framework can progress
  while SimNow is unavailable, locked, or under settlement initialization.

The service is deliberately safe by default: it does not auto-connect to SimNow
unless --connect is passed. This avoids repeated failed trade logins while a
SimNow account is locked or under settlement initialization.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from vnpy.event import Event, EventEngine
from vnpy.trader.constant import Exchange
from vnpy.trader.engine import MainEngine
from vnpy.trader.event import EVENT_LOG, EVENT_TICK
from vnpy.trader.object import SubscribeRequest
from vnpy_ctp import CtpGateway


CONFIG_PATH = Path("config.json")
DEFAULT_MOCK_SYMBOLS = ["au2606.SHFE"]
DEFAULT_MOCK_INTERVAL_SECONDS = 1.0

startup_mock_symbols: list[str] = []
startup_mock_interval_seconds = DEFAULT_MOCK_INTERVAL_SECONDS


@dataclass(slots=True)
class TickMessage:
    vt_symbol: str
    symbol: str
    exchange: str
    datetime: str | None
    last_price: float
    bid_price_1: float
    bid_volume_1: float
    ask_price_1: float
    ask_volume_1: float
    volume: float
    open_interest: float
    source: str = "unknown"


class SubscribePayload(BaseModel):
    symbols: list[str]


class MockStartPayload(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: DEFAULT_MOCK_SYMBOLS.copy())
    intervalSeconds: float = Field(default=DEFAULT_MOCK_INTERVAL_SECONDS, gt=0)


class BridgeState:
    def __init__(self) -> None:
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self.connected = False
        self.subscriptions: set[str] = set()
        self.last_log: str | None = None
        self.last_tick: TickMessage | None = None
        self.websocket_clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.event_engine: EventEngine | None = None
        self.main_engine: MainEngine | None = None
        self.mock_running = False
        self.mock_symbols: set[str] = set()
        self.mock_interval_seconds = DEFAULT_MOCK_INTERVAL_SECONDS
        self.mock_task: asyncio.Task | None = None
        self.mock_prices: dict[str, float] = {}
        self.mock_volumes: dict[str, float] = {}
        self.lock = threading.RLock()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "startedAt": self.started_at,
                "connected": self.connected,
                "subscriptions": sorted(self.subscriptions),
                "lastLog": self.last_log,
                "lastTick": asdict(self.last_tick) if self.last_tick else None,
                "websocketClients": len(self.websocket_clients),
                "mockRunning": self.mock_running,
                "mockSymbols": sorted(self.mock_symbols),
                "mockIntervalSeconds": self.mock_interval_seconds,
            }


state = BridgeState()
app = FastAPI(title="Quant Simulation Python Bridge")


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Missing {CONFIG_PATH.resolve()}. Copy config.example.json to config.json first."
        )

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    required = [
        "investorId",
        "password",
        "brokerId",
        "tdAddress",
        "mdAddress",
        "appId",
        "authCode",
    ]
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise ValueError(f"config.json missing required keys: {missing}")
    return config


def build_setting(config: dict) -> dict:
    return {
        "用户名": config["investorId"],
        "密码": config["password"],
        "经纪商代码": config["brokerId"],
        "交易服务器": config["tdAddress"],
        "行情服务器": config["mdAddress"],
        "产品名称": config["appId"],
        "授权编码": config["authCode"],
    }


def parse_vt_symbol(vt_symbol: str) -> tuple[str, str]:
    if "." not in vt_symbol:
        raise ValueError(f"Invalid vt_symbol: {vt_symbol}. Example: au2606.SHFE")

    symbol, exchange_name = vt_symbol.split(".", 1)
    if not symbol or not exchange_name:
        raise ValueError(f"Invalid vt_symbol: {vt_symbol}. Example: au2606.SHFE")
    return symbol, exchange_name


def to_subscribe_request(vt_symbol: str) -> SubscribeRequest:
    symbol, exchange_name = parse_vt_symbol(vt_symbol)
    return SubscribeRequest(symbol=symbol, exchange=Exchange(exchange_name))


async def broadcast_tick(message: TickMessage) -> None:
    payload = json.dumps({"type": "tick", "data": asdict(message)}, ensure_ascii=False)
    dead_clients: list[WebSocket] = []

    for ws in list(state.websocket_clients):
        try:
            await ws.send_text(payload)
        except Exception:
            dead_clients.append(ws)

    for ws in dead_clients:
        state.websocket_clients.discard(ws)


def publish_tick(message: TickMessage) -> None:
    with state.lock:
        state.last_tick = message

    print("[TICK]", asdict(message))
    if state.loop:
        asyncio.run_coroutine_threadsafe(broadcast_tick(message), state.loop)


def on_log(event: Event) -> None:
    log = event.data
    msg = getattr(log, "msg", str(log))
    gateway_name = getattr(log, "gateway_name", "")
    line = f"[{gateway_name}] {msg}"
    with state.lock:
        state.last_log = line
    print("[LOG]", line)


def on_tick(event: Event) -> None:
    tick = event.data
    message = TickMessage(
        vt_symbol=tick.vt_symbol,
        symbol=tick.symbol,
        exchange=tick.exchange.value,
        datetime=tick.datetime.isoformat() if tick.datetime else None,
        last_price=tick.last_price,
        bid_price_1=tick.bid_price_1,
        bid_volume_1=tick.bid_volume_1,
        ask_price_1=tick.ask_price_1,
        ask_volume_1=tick.ask_volume_1,
        volume=tick.volume,
        open_interest=tick.open_interest,
        source="simnow",
    )
    publish_tick(message)


def connect_gateway() -> None:
    config = load_config()
    event_engine = EventEngine()
    main_engine = MainEngine(event_engine)

    event_engine.register(EVENT_LOG, on_log)
    event_engine.register(EVENT_TICK, on_tick)
    main_engine.add_gateway(CtpGateway)
    main_engine.connect(build_setting(config), "CTP")

    with state.lock:
        state.event_engine = event_engine
        state.main_engine = main_engine
        state.connected = True


def subscribe(vt_symbols: list[str]) -> None:
    if not state.main_engine:
        raise RuntimeError("Gateway is not connected. Start server with --connect or call /connect first.")

    for vt_symbol in vt_symbols:
        req = to_subscribe_request(vt_symbol)
        state.main_engine.subscribe(req, "CTP")
        with state.lock:
            state.subscriptions.add(vt_symbol)
        time.sleep(0.2)


def initial_mock_price(vt_symbol: str) -> float:
    symbol, _exchange = parse_vt_symbol(vt_symbol)
    lower_symbol = symbol.lower()
    if lower_symbol.startswith("au"):
        return 560.0
    if lower_symbol.startswith("ag"):
        return 8200.0
    if lower_symbol.startswith("rb"):
        return 3300.0
    if lower_symbol.startswith("cu"):
        return 78000.0
    if lower_symbol.startswith("al"):
        return 20500.0
    if lower_symbol.startswith("if"):
        return 3900.0
    return 100.0


def make_mock_tick(vt_symbol: str) -> TickMessage:
    symbol, exchange = parse_vt_symbol(vt_symbol)

    price = state.mock_prices.setdefault(vt_symbol, initial_mock_price(vt_symbol))
    volume = state.mock_volumes.setdefault(vt_symbol, 0.0)

    drift = random.uniform(-0.0015, 0.0015)
    next_price = max(0.01, round(price * (1 + drift), 2))
    spread = max(0.01, round(next_price * 0.0002, 2))
    next_volume = volume + random.randint(1, 20)

    state.mock_prices[vt_symbol] = next_price
    state.mock_volumes[vt_symbol] = next_volume

    return TickMessage(
        vt_symbol=vt_symbol,
        symbol=symbol,
        exchange=exchange,
        datetime=datetime.now().isoformat(timespec="milliseconds"),
        last_price=next_price,
        bid_price_1=round(next_price - spread, 2),
        bid_volume_1=random.randint(1, 100),
        ask_price_1=round(next_price + spread, 2),
        ask_volume_1=random.randint(1, 100),
        volume=next_volume,
        open_interest=10000 + random.randint(-500, 500),
        source="mock",
    )


async def mock_tick_loop() -> None:
    print("[MOCK] tick source started")
    try:
        while True:
            with state.lock:
                symbols = sorted(state.mock_symbols)
                interval_seconds = state.mock_interval_seconds

            for vt_symbol in symbols:
                publish_tick(make_mock_tick(vt_symbol))

            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        print("[MOCK] tick source stopped")
        raise


def start_mock_source(symbols: list[str], interval_seconds: float) -> None:
    if not state.loop:
        raise RuntimeError("Event loop is not ready")

    for vt_symbol in symbols:
        parse_vt_symbol(vt_symbol)

    with state.lock:
        state.mock_symbols = set(symbols)
        state.mock_interval_seconds = interval_seconds
        state.mock_running = True
        if state.mock_task and not state.mock_task.done():
            state.mock_task.cancel()
        state.mock_task = state.loop.create_task(mock_tick_loop())


def stop_mock_source() -> None:
    with state.lock:
        state.mock_running = False
        if state.mock_task and not state.mock_task.done():
            state.mock_task.cancel()
        state.mock_task = None


@app.on_event("startup")
async def on_startup() -> None:
    state.loop = asyncio.get_running_loop()
    if startup_mock_symbols:
        start_mock_source(startup_mock_symbols, startup_mock_interval_seconds)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    stop_mock_source()
    if state.main_engine:
        state.main_engine.close()


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, **state.snapshot()}


@app.get("/config")
def config_view() -> dict[str, Any]:
    config = load_config()
    return {
        "investorId": config["investorId"],
        "brokerId": config["brokerId"],
        "tdAddress": config["tdAddress"],
        "mdAddress": config["mdAddress"],
        "appId": config["appId"],
        "authCodeMasked": "***" if config.get("authCode") else None,
        "passwordMasked": "***" if config.get("password") else None,
    }


@app.post("/connect")
def connect() -> dict[str, Any]:
    if state.connected:
        return {"ok": True, "message": "already connected", **state.snapshot()}

    connect_gateway()
    return {"ok": True, "message": "connect requested", **state.snapshot()}


@app.post("/subscribe")
def subscribe_endpoint(payload: SubscribePayload) -> dict[str, Any]:
    subscribe(payload.symbols)
    return {"ok": True, **state.snapshot()}


@app.post("/mock/start")
def mock_start(payload: MockStartPayload) -> dict[str, Any]:
    start_mock_source(payload.symbols, payload.intervalSeconds)
    return {"ok": True, "message": "mock tick source started", **state.snapshot()}


@app.post("/mock/stop")
def mock_stop() -> dict[str, Any]:
    stop_mock_source()
    return {"ok": True, "message": "mock tick source stopped", **state.snapshot()}


@app.websocket("/ws/ticks")
async def websocket_ticks(ws: WebSocket) -> None:
    await ws.accept()
    state.websocket_clients.add(ws)
    try:
        await ws.send_text(json.dumps({"type": "snapshot", "data": state.snapshot()}, ensure_ascii=False))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        state.websocket_clients.discard(ws)


def main() -> None:
    global startup_mock_symbols, startup_mock_interval_seconds

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--connect", action="store_true")
    parser.add_argument("--subscribe", nargs="*", default=[])
    parser.add_argument("--mock", nargs="*", default=[])
    parser.add_argument("--mock-interval", default=DEFAULT_MOCK_INTERVAL_SECONDS, type=float)
    args = parser.parse_args()

    if args.connect:
        connect_gateway()
        if args.subscribe:
            time.sleep(15)
            subscribe(args.subscribe)

    if args.mock:
        startup_mock_symbols = args.mock
        startup_mock_interval_seconds = args.mock_interval

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
