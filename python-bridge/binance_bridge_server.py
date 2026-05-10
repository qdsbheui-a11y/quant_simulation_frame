"""Binance spot market data bridge for the simulation framework.

This server connects to Binance public spot bookTicker websocket streams, converts
bid/ask quotes into the local Tick model, feeds them into SimulationEngine, and
exposes the same basic simulation HTTP/WebSocket APIs used by local mock mode.

No Binance API key is required because only public market data is consumed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import threading
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from realtime import BuyAndHoldOnFirstTickStrategy, RealtimeStrategyRunner
from simulation.engine import SimulationEngine
from simulation.models import Direction, Offset, OrderRequest, OrderType, SimulationConfig, Tick


BINANCE_STREAM_BASE_URL = "wss://data-stream.binance.vision/stream?streams="
DEFAULT_BINANCE_SYMBOLS = ["BTCUSDT"]
DEFAULT_RECONNECT_DELAY_SECONDS = 3.0
MAX_RECONNECT_DELAY_SECONDS = 30.0
MARKET_DATA_STALE_SECONDS = 10.0

startup_binance_symbols: list[str] = []
startup_strategy_name: str | None = None
startup_strategy_volume: float = 1.0


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


class BinanceStartPayload(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: DEFAULT_BINANCE_SYMBOLS.copy())


class StrategyStartPayload(BaseModel):
    name: str = "buy-and-hold"
    symbols: list[str] = Field(default_factory=list)
    volume: float = Field(default=1.0, gt=0)


class BridgeState:
    def __init__(self) -> None:
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self.websocket_clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.binance_running = False
        self.binance_symbols: set[str] = set()
        self.binance_task: asyncio.Task | None = None
        self.last_tick: dict[str, Any] | None = None
        self.last_tick_received_at: datetime | None = None
        self.last_log: str | None = None
        self.reconnect_attempts = 0
        self.current_reconnect_delay_seconds = DEFAULT_RECONNECT_DELAY_SECONDS
        self.simulation = SimulationEngine()
        self.strategy_runner: RealtimeStrategyRunner | None = None
        self.strategy_name: str | None = None
        self.strategy_symbols: set[str] = set()
        self.strategy_volume: float = 0.0
        self.last_strategy_orders: list[dict[str, Any]] = []
        self.lock = threading.RLock()

    def tick_age_seconds(self) -> float | None:
        if not self.last_tick_received_at:
            return None
        return round((datetime.now() - self.last_tick_received_at).total_seconds(), 3)

    def strategy_snapshot(self) -> dict[str, Any]:
        runner = self.strategy_runner
        return {
            "enabled": runner.enabled if runner else False,
            "name": self.strategy_name,
            "symbols": sorted(self.strategy_symbols),
            "volume": self.strategy_volume,
            "generatedOrders": runner.generated_orders if runner else 0,
            "lastError": runner.last_error if runner else None,
            "lastOrders": self.last_strategy_orders,
        }

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            tick_age = self.tick_age_seconds()
            return {
                "startedAt": self.started_at,
                "source": "binance",
                "binanceRunning": self.binance_running,
                "binanceSymbols": sorted(self.binance_symbols),
                "lastLog": self.last_log,
                "lastTick": to_jsonable(self.last_tick),
                "lastTickReceivedAt": to_jsonable(self.last_tick_received_at),
                "lastTickAgeSeconds": tick_age,
                "marketDataFresh": tick_age is not None and tick_age <= MARKET_DATA_STALE_SECONDS,
                "reconnectAttempts": self.reconnect_attempts,
                "currentReconnectDelaySeconds": self.current_reconnect_delay_seconds,
                "websocketClients": len(self.websocket_clients),
                "strategy": self.strategy_snapshot(),
                "simulation": to_jsonable(self.simulation.snapshot()),
            }


state = BridgeState()
app = FastAPI(title="Quant Simulation Binance Bridge")


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


def normalize_binance_symbol(symbol: str) -> str:
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("Binance symbol cannot be empty. Example: BTCUSDT")
    if "." in symbol:
        symbol = symbol.split(".", 1)[0]
    return symbol


def binance_to_vt_symbol(symbol: str) -> str:
    return f"{normalize_binance_symbol(symbol)}.BINANCE"


def parse_vt_symbol(vt_symbol: str) -> tuple[str, str]:
    if "." not in vt_symbol:
        raise ValueError("Invalid vtSymbol. Binance example: BTCUSDT.BINANCE")
    symbol, exchange = vt_symbol.split(".", 1)
    if not symbol or not exchange:
        raise ValueError("Invalid vtSymbol. Binance example: BTCUSDT.BINANCE")
    return symbol, exchange


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
        if state.strategy_runner:
            restart_realtime_strategy_locked(state.strategy_name, list(state.strategy_symbols), state.strategy_volume)


def restart_realtime_strategy_locked(name: str | None, symbols: list[str], volume: float) -> None:
    if not name:
        state.strategy_runner = None
        state.strategy_name = None
        state.strategy_symbols = set()
        state.strategy_volume = 0.0
        state.last_strategy_orders = []
        return

    normalized_name = name.strip().lower()
    vt_symbols = {binance_to_vt_symbol(symbol) for symbol in symbols}
    if normalized_name in {"buy-and-hold", "buy_and_hold", "hold"}:
        strategy = BuyAndHoldOnFirstTickStrategy(symbols=vt_symbols, volume=volume)
    else:
        raise ValueError(f"unsupported realtime strategy: {name}")

    state.strategy_runner = RealtimeStrategyRunner(strategy=strategy, engine=state.simulation)
    state.strategy_name = "buy-and-hold"
    state.strategy_symbols = vt_symbols
    state.strategy_volume = volume
    state.last_strategy_orders = []


def start_realtime_strategy(name: str, symbols: list[str], volume: float) -> None:
    if not symbols:
        with state.lock:
            symbols = sorted(state.binance_symbols)
    with state.lock:
        restart_realtime_strategy_locked(name, symbols, volume)


def stop_realtime_strategy() -> None:
    with state.lock:
        restart_realtime_strategy_locked(None, [], 0.0)


def apply_realtime_strategy(tick: Tick) -> list[dict[str, Any]]:
    with state.lock:
        runner = state.strategy_runner
        if not runner:
            return []
        requests = runner.on_tick(tick)
        orders = [state.simulation.submit_order(request) for request in requests]
        payload = [to_jsonable(order) for order in orders]
        if payload:
            state.last_strategy_orders = payload
            emit_ws_event("strategy.orders", payload)
        return payload


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "--"):
            return default
        return float(value)
    except Exception:
        return default


def binance_book_ticker_to_tick(data: dict[str, Any]) -> Tick:
    symbol = normalize_binance_symbol(str(data["s"]))
    vt_symbol = f"{symbol}.BINANCE"
    bid = _to_float(data.get("b"))
    ask = _to_float(data.get("a"))
    last = round((bid + ask) / 2, 8) if bid > 0 and ask > 0 else max(bid, ask)

    return Tick(
        vt_symbol=vt_symbol,
        symbol=symbol,
        exchange="BINANCE",
        datetime=datetime.now(),
        last_price=last,
        bid_price_1=bid,
        bid_volume_1=_to_float(data.get("B")),
        ask_price_1=ask,
        ask_volume_1=_to_float(data.get("A")),
        volume=0.0,
        open_interest=0.0,
        source="binance",
    )


def publish_tick(tick: Tick) -> None:
    tick_payload = to_jsonable(tick)
    with state.lock:
        state.last_tick = tick_payload
        state.last_tick_received_at = datetime.now()
        state.simulation.on_tick(tick)
    strategy_orders = apply_realtime_strategy(tick)
    print("[BINANCE_TICK]", tick_payload)
    if strategy_orders:
        print("[STRATEGY_ORDERS]", strategy_orders)
    emit_ws_event("tick", tick_payload)


async def binance_tick_loop() -> None:
    import websockets

    print("[BINANCE] tick source started")
    try:
        while True:
            with state.lock:
                symbols = sorted(state.binance_symbols)

            if not symbols:
                await asyncio.sleep(1)
                continue

            streams = "/".join(f"{symbol.lower()}@bookTicker" for symbol in symbols)
            url = f"{BINANCE_STREAM_BASE_URL}{streams}"
            with state.lock:
                state.last_log = f"connecting {url}"
            print(f"[BINANCE] connecting: {url}")

            try:
                async with websockets.connect(
                    url,
                    open_timeout=10,
                    ping_interval=20,
                    ping_timeout=60,
                    close_timeout=5,
                ) as ws:
                    with state.lock:
                        state.last_log = "binance connected"
                        state.reconnect_attempts = 0
                        state.current_reconnect_delay_seconds = DEFAULT_RECONNECT_DELAY_SECONDS
                    print("[BINANCE] connected")

                    async for message in ws:
                        raw = json.loads(message)
                        data = raw.get("data", raw)
                        if "s" not in data:
                            continue
                        tick = binance_book_ticker_to_tick(data)
                        publish_tick(tick)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                with state.lock:
                    state.reconnect_attempts += 1
                    delay = min(
                        DEFAULT_RECONNECT_DELAY_SECONDS * (2 ** min(state.reconnect_attempts - 1, 4)),
                        MAX_RECONNECT_DELAY_SECONDS,
                    )
                    state.current_reconnect_delay_seconds = delay
                    state.last_log = (
                        f"binance reconnect after {type(exc).__name__}: {exc}; "
                        f"retry in {delay}s"
                    )
                print(f"[BINANCE] reconnect after error: {type(exc).__name__}: {exc}; retry in {delay}s")
                await asyncio.sleep(delay)
    except asyncio.CancelledError:
        print("[BINANCE] tick source stopped")
        raise


def start_binance_source(symbols: list[str]) -> None:
    if not state.loop:
        raise RuntimeError("Event loop is not ready")
    normalized = [normalize_binance_symbol(symbol) for symbol in symbols]
    with state.lock:
        state.binance_symbols = set(normalized)
        state.binance_running = True
        state.reconnect_attempts = 0
        state.current_reconnect_delay_seconds = DEFAULT_RECONNECT_DELAY_SECONDS
        if state.binance_task and not state.binance_task.done():
            state.binance_task.cancel()
        state.binance_task = state.loop.create_task(binance_tick_loop())


def stop_binance_source() -> None:
    with state.lock:
        state.binance_running = False
        if state.binance_task and not state.binance_task.done():
            state.binance_task.cancel()
        state.binance_task = None


@app.on_event("startup")
async def on_startup() -> None:
    state.loop = asyncio.get_running_loop()
    wire_simulation_callbacks()
    if startup_strategy_name and startup_binance_symbols:
        start_realtime_strategy(startup_strategy_name, startup_binance_symbols, startup_strategy_volume)
    if startup_binance_symbols:
        start_binance_source(startup_binance_symbols)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    stop_binance_source()


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, **state.snapshot()}


@app.post("/binance/start")
def binance_start(payload: BinanceStartPayload) -> dict[str, Any]:
    start_binance_source(payload.symbols)
    return {"ok": True, "message": "binance tick source started", **state.snapshot()}


@app.post("/binance/stop")
def binance_stop() -> dict[str, Any]:
    stop_binance_source()
    return {"ok": True, "message": "binance tick source stopped", **state.snapshot()}


@app.post("/strategy/start")
def strategy_start(payload: StrategyStartPayload) -> dict[str, Any]:
    start_realtime_strategy(payload.name, payload.symbols, payload.volume)
    return {"ok": True, "message": "strategy started", "strategy": state.strategy_snapshot()}


@app.post("/strategy/stop")
def strategy_stop() -> dict[str, Any]:
    stop_realtime_strategy()
    return {"ok": True, "message": "strategy stopped", "strategy": state.strategy_snapshot()}


@app.get("/strategy/status")
def strategy_status() -> dict[str, Any]:
    return {"ok": True, "data": state.strategy_snapshot()}


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
    global startup_binance_symbols, startup_strategy_name, startup_strategy_volume

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--binance", nargs="*", default=[])
    parser.add_argument("--strategy", choices=["buy-and-hold"], default=None)
    parser.add_argument("--strategy-volume", type=float, default=1.0)
    args = parser.parse_args()

    if args.binance:
        startup_binance_symbols = [normalize_binance_symbol(symbol) for symbol in args.binance]
    if args.strategy:
        startup_strategy_name = args.strategy
        startup_strategy_volume = args.strategy_volume

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
