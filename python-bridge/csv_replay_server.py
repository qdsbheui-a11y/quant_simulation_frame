"""Streaming CSV replay bridge for the simulation framework.

The replay reads CSV rows incrementally instead of loading the whole file into
memory. Each row is converted into the local Tick model, pushed into
SimulationEngine, and broadcast to websocket clients.

Expected CSV columns:

    vt_symbol,datetime,last_price,bid_price_1,ask_price_1

Optional columns:

    symbol,exchange,bid_volume_1,ask_volume_1,volume,open_interest

Example vt_symbol values:

    BTCUSDT.BINANCE
    au2606.SHFE
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import threading
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from simulation.engine import SimulationEngine
from simulation.models import Direction, Offset, OrderRequest, OrderType, SimulationConfig, Tick


DEFAULT_REPLAY_INTERVAL_SECONDS = 0.1
startup_csv_path: str | None = None
startup_loop_replay = False
startup_replay_interval_seconds = DEFAULT_REPLAY_INTERVAL_SECONDS


class CsvStartPayload(BaseModel):
    filePath: str
    intervalSeconds: float = Field(default=DEFAULT_REPLAY_INTERVAL_SECONDS, ge=0)
    loop: bool = False


class SimulationResetPayload(BaseModel):
    initialBalance: float = Field(default=1_000_000.0, gt=0)
    commissionRate: float = Field(default=0.0001, ge=0)
    slippage: float = Field(default=0.0, ge=0)


class SimulationOrderPayload(BaseModel):
    vtSymbol: str
    direction: str
    offset: str = "OPEN"
    price: float = Field(gt=0)
    volume: float = Field(gt=0)
    orderType: str = "LIMIT"


class BridgeState:
    def __init__(self) -> None:
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self.websocket_clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.csv_running = False
        self.csv_path: str | None = None
        self.csv_loop_replay = False
        self.csv_interval_seconds = DEFAULT_REPLAY_INTERVAL_SECONDS
        self.csv_task: asyncio.Task | None = None
        self.csv_rows_replayed = 0
        self.csv_completed = False
        self.last_tick: dict[str, Any] | None = None
        self.last_tick_received_at: datetime | None = None
        self.last_log: str | None = None
        self.simulation = SimulationEngine()
        self.lock = threading.RLock()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "startedAt": self.started_at,
                "source": "csv",
                "csvRunning": self.csv_running,
                "csvPath": self.csv_path,
                "csvLoopReplay": self.csv_loop_replay,
                "csvIntervalSeconds": self.csv_interval_seconds,
                "csvRowsReplayed": self.csv_rows_replayed,
                "csvCompleted": self.csv_completed,
                "lastLog": self.last_log,
                "lastTick": to_jsonable(self.last_tick),
                "lastTickReceivedAt": to_jsonable(self.last_tick_received_at),
                "websocketClients": len(self.websocket_clients),
                "simulation": to_jsonable(self.simulation.snapshot()),
            }


state = BridgeState()
app = FastAPI(title="Quant Simulation CSV Replay Bridge")


def to_jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {key: to_jsonable(val) for key, val in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    return value


def parse_enum(enum_type: type[Enum], value: str) -> Enum:
    normalized = value.upper()
    try:
        return enum_type(normalized)
    except ValueError:
        return enum_type[normalized]


def parse_vt_symbol(vt_symbol: str) -> tuple[str, str]:
    if "." not in vt_symbol:
        raise ValueError(f"Invalid vt_symbol: {vt_symbol}. Example: BTCUSDT.BINANCE")
    symbol, exchange = vt_symbol.split(".", 1)
    if not symbol or not exchange:
        raise ValueError(f"Invalid vt_symbol: {vt_symbol}. Example: BTCUSDT.BINANCE")
    return symbol, exchange


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "--"):
            return default
        return float(value)
    except Exception:
        return default


def parse_datetime(value: Any) -> datetime:
    if value in (None, ""):
        return datetime.now()
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return datetime.now()


def row_to_tick(row: dict[str, str]) -> Tick:
    vt_symbol = row.get("vt_symbol") or row.get("vtSymbol") or row.get("symbol")
    if not vt_symbol:
        raise ValueError("CSV row missing vt_symbol/vtSymbol/symbol")

    if "." in vt_symbol:
        symbol, exchange = parse_vt_symbol(vt_symbol)
    else:
        symbol = vt_symbol
        exchange = row.get("exchange") or "UNKNOWN"
        vt_symbol = f"{symbol}.{exchange}"

    bid = to_float(row.get("bid_price_1") or row.get("bidPrice1") or row.get("bid"))
    ask = to_float(row.get("ask_price_1") or row.get("askPrice1") or row.get("ask"))
    last = to_float(row.get("last_price") or row.get("lastPrice") or row.get("last"))
    if last <= 0 and bid > 0 and ask > 0:
        last = round((bid + ask) / 2, 8)

    return Tick(
        vt_symbol=vt_symbol,
        symbol=row.get("symbol") or symbol,
        exchange=row.get("exchange") or exchange,
        datetime=parse_datetime(row.get("datetime") or row.get("time") or row.get("timestamp")),
        last_price=last,
        bid_price_1=bid,
        bid_volume_1=to_float(row.get("bid_volume_1") or row.get("bidVolume1") or row.get("bid_volume")),
        ask_price_1=ask,
        ask_volume_1=to_float(row.get("ask_volume_1") or row.get("askVolume1") or row.get("ask_volume")),
        volume=to_float(row.get("volume")),
        open_interest=to_float(row.get("open_interest") or row.get("openInterest")),
        source="csv",
    )


def iter_csv_ticks(path: Path) -> Iterator[Tick]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield row_to_tick(row)


async def broadcast_payload(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    dead_clients: list[WebSocket] = []
    for ws in list(state.websocket_clients):
        try:
            await ws.send_text(text)
        except Exception:
            dead_clients.append(ws)
    for ws in dead_clients:
        state.websocket_clients.discard(ws)


def emit_ws_event(event_type: str, data: Any) -> None:
    payload = {"type": event_type, "data": to_jsonable(data)}
    if state.loop:
        asyncio.run_coroutine_threadsafe(broadcast_payload(payload), state.loop)


def wire_simulation_callbacks() -> None:
    state.simulation.on_order(lambda order: emit_ws_event("simulation.order", order))
    state.simulation.on_trade(lambda trade: emit_ws_event("simulation.trade", trade))
    state.simulation.on_account(lambda account: emit_ws_event("simulation.account", account))
    state.simulation.on_position(lambda position: emit_ws_event("simulation.position", position))


def reset_simulation(config: SimulationConfig | None = None) -> None:
    with state.lock:
        state.simulation = SimulationEngine(config)
        wire_simulation_callbacks()


def publish_tick(tick: Tick) -> None:
    tick_payload = to_jsonable(tick)
    with state.lock:
        state.last_tick = tick_payload
        state.last_tick_received_at = datetime.now()
        state.csv_rows_replayed += 1
        state.simulation.on_tick(tick)
    print("[CSV_TICK]", tick_payload)
    emit_ws_event("tick", tick_payload)


async def csv_replay_loop(path: Path, interval_seconds: float, loop_replay: bool) -> None:
    print(f"[CSV] replay started: {path}")
    try:
        while True:
            replayed_this_round = 0
            for tick in iter_csv_ticks(path):
                publish_tick(tick)
                replayed_this_round += 1
                if interval_seconds > 0:
                    await asyncio.sleep(interval_seconds)
                else:
                    await asyncio.sleep(0)

            with state.lock:
                state.csv_completed = True
                state.last_log = f"csv replay completed: {replayed_this_round} rows"
            print(f"[CSV] replay completed: {replayed_this_round} rows")

            if not loop_replay:
                with state.lock:
                    state.csv_running = False
                return
    except asyncio.CancelledError:
        print("[CSV] replay stopped")
        raise


def start_csv_replay(file_path: str, interval_seconds: float, loop_replay: bool) -> None:
    if not state.loop:
        raise RuntimeError("Event loop is not ready")

    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    with state.lock:
        state.csv_path = str(path)
        state.csv_loop_replay = loop_replay
        state.csv_interval_seconds = interval_seconds
        state.csv_running = True
        state.csv_completed = False
        state.csv_rows_replayed = 0
        state.last_log = f"starting csv replay: {path}"
        if state.csv_task and not state.csv_task.done():
            state.csv_task.cancel()
        state.csv_task = state.loop.create_task(csv_replay_loop(path, interval_seconds, loop_replay))


def stop_csv_replay() -> None:
    with state.lock:
        state.csv_running = False
        if state.csv_task and not state.csv_task.done():
            state.csv_task.cancel()
        state.csv_task = None


@app.on_event("startup")
async def on_startup() -> None:
    state.loop = asyncio.get_running_loop()
    wire_simulation_callbacks()
    if startup_csv_path:
        start_csv_replay(startup_csv_path, startup_replay_interval_seconds, startup_loop_replay)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    stop_csv_replay()


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, **state.snapshot()}


@app.post("/csv/start")
def csv_start(payload: CsvStartPayload) -> dict[str, Any]:
    start_csv_replay(payload.filePath, payload.intervalSeconds, payload.loop)
    return {"ok": True, "message": "csv replay started", **state.snapshot()}


@app.post("/csv/stop")
def csv_stop() -> dict[str, Any]:
    stop_csv_replay()
    return {"ok": True, "message": "csv replay stopped", **state.snapshot()}


@app.post("/simulation/reset")
def simulation_reset(payload: SimulationResetPayload) -> dict[str, Any]:
    config = SimulationConfig(
        initial_balance=payload.initialBalance,
        commission_rate=payload.commissionRate,
        slippage=payload.slippage,
    )
    reset_simulation(config)
    return {"ok": True, "message": "simulation reset", "simulation": to_jsonable(state.simulation.snapshot())}


@app.get("/simulation/account")
def simulation_account() -> dict[str, Any]:
    return {"ok": True, "data": to_jsonable(state.simulation.account)}


@app.get("/simulation/positions")
def simulation_positions() -> dict[str, Any]:
    return {"ok": True, "data": to_jsonable(list(state.simulation.positions.values()))}


@app.get("/simulation/orders")
def simulation_orders() -> dict[str, Any]:
    return {"ok": True, "data": to_jsonable(list(state.simulation.orders.values()))}


@app.get("/simulation/trades")
def simulation_trades() -> dict[str, Any]:
    return {"ok": True, "data": to_jsonable(list(state.simulation.trades.values()))}


@app.get("/simulation/snapshot")
def simulation_snapshot() -> dict[str, Any]:
    return {"ok": True, "data": to_jsonable(state.simulation.snapshot())}


@app.post("/simulation/orders")
def simulation_submit_order(payload: SimulationOrderPayload) -> dict[str, Any]:
    parse_vt_symbol(payload.vtSymbol)
    request = OrderRequest(
        vt_symbol=payload.vtSymbol,
        direction=parse_enum(Direction, payload.direction),
        offset=parse_enum(Offset, payload.offset),
        price=payload.price,
        volume=payload.volume,
        order_type=parse_enum(OrderType, payload.orderType),
    )
    order = state.simulation.submit_order(request)
    return {"ok": True, "data": to_jsonable(order), "simulation": to_jsonable(state.simulation.snapshot())}


@app.post("/simulation/orders/{order_id}/cancel")
def simulation_cancel_order(order_id: str) -> dict[str, Any]:
    order = state.simulation.cancel_order(order_id)
    return {"ok": order is not None, "data": to_jsonable(order), "simulation": to_jsonable(state.simulation.snapshot())}


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
    global startup_csv_path, startup_loop_replay, startup_replay_interval_seconds

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--csv", default=None)
    parser.add_argument("--interval", default=DEFAULT_REPLAY_INTERVAL_SECONDS, type=float)
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()

    if args.csv:
        startup_csv_path = args.csv
        startup_replay_interval_seconds = args.interval
        startup_loop_replay = args.loop

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
