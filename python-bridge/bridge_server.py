"""Python bridge service for the simulation framework.

Current scope:
- exposes health/config endpoints;
- optionally connects to SimNow through vn.py CTP gateway;
- broadcasts ticks to WebSocket clients as JSON.

The service is deliberately safe by default: it does not auto-connect to SimNow
unless --connect is passed. This avoids repeated failed trade logins while a
SimNow account is locked or under settlement initialization.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from vnpy.event import Event, EventEngine
from vnpy.trader.constant import Exchange
from vnpy.trader.engine import MainEngine
from vnpy.trader.event import EVENT_LOG, EVENT_TICK
from vnpy.trader.object import SubscribeRequest
from vnpy_ctp import CtpGateway


CONFIG_PATH = Path("config.json")


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


class SubscribePayload(BaseModel):
    symbols: list[str]


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


def parse_vt_symbol(vt_symbol: str) -> SubscribeRequest:
    if "." not in vt_symbol:
        raise ValueError(f"Invalid vt_symbol: {vt_symbol}. Example: au2606.SHFE")

    symbol, exchange_name = vt_symbol.split(".", 1)
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
    )

    with state.lock:
        state.last_tick = message

    print("[TICK]", asdict(message))
    if state.loop:
        asyncio.run_coroutine_threadsafe(broadcast_tick(message), state.loop)


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
        req = parse_vt_symbol(vt_symbol)
        state.main_engine.subscribe(req, "CTP")
        with state.lock:
            state.subscriptions.add(vt_symbol)
        time.sleep(0.2)


@app.on_event("startup")
async def on_startup() -> None:
    state.loop = asyncio.get_running_loop()


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
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--connect", action="store_true")
    parser.add_argument("--subscribe", nargs="*", default=[])
    args = parser.parse_args()

    if args.connect:
        connect_gateway()
        if args.subscribe:
            time.sleep(15)
            subscribe(args.subscribe)

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
