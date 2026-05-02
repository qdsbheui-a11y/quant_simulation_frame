"""SimNow market-data smoke test through vn.py CTP gateway.

This script intentionally uses CtpGateway instead of directly using MdApi because
vn.py handles the CTP handshake and event conversion consistently across package
versions.

Usage:
    python run_gateway_md.py au2606.SHFE rb2610.SHFE IF2606.CFFEX
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from vnpy.event import Event, EventEngine
from vnpy.trader.constant import Exchange
from vnpy.trader.engine import MainEngine
from vnpy.trader.event import EVENT_LOG, EVENT_TICK
from vnpy.trader.object import SubscribeRequest

from vnpy_ctp import CtpGateway


CONFIG_PATH = Path("config.json")


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


def on_log(event: Event) -> None:
    log = event.data
    msg = getattr(log, "msg", str(log))
    gateway_name = getattr(log, "gateway_name", "")
    print(f"[LOG][{gateway_name}] {msg}")


def on_tick(event: Event) -> None:
    tick = event.data
    print(
        "[TICK]",
        tick.vt_symbol,
        "datetime=", tick.datetime,
        "last=", tick.last_price,
        "bid1=", tick.bid_price_1,
        "bidVol1=", tick.bid_volume_1,
        "ask1=", tick.ask_price_1,
        "askVol1=", tick.ask_volume_1,
        "volume=", tick.volume,
        "openInterest=", tick.open_interest,
    )


def parse_subscriptions() -> list[SubscribeRequest]:
    args = sys.argv[1:] or ["au2606.SHFE"]
    requests: list[SubscribeRequest] = []

    for item in args:
        if "." not in item:
            raise ValueError(
                f"Invalid symbol: {item}. Use vt_symbol format, for example au2606.SHFE."
            )

        symbol, exchange_name = item.split(".", 1)
        requests.append(SubscribeRequest(symbol=symbol, exchange=Exchange(exchange_name)))

    return requests


def main() -> None:
    config = load_config()
    subscriptions = parse_subscriptions()

    print("[MAIN] config:", CONFIG_PATH.resolve())
    print("[MAIN] investorId:", config["investorId"])
    print("[MAIN] brokerId:", config["brokerId"])
    print("[MAIN] tdAddress:", config["tdAddress"])
    print("[MAIN] mdAddress:", config["mdAddress"])
    print("[MAIN] subscriptions:", [f"{r.symbol}.{r.exchange.value}" for r in subscriptions])

    event_engine = EventEngine()
    main_engine = MainEngine(event_engine)

    event_engine.register(EVENT_LOG, on_log)
    event_engine.register(EVENT_TICK, on_tick)
    main_engine.add_gateway(CtpGateway)

    print("[MAIN] connecting CTP gateway")
    main_engine.connect(build_setting(config), "CTP")

    print("[MAIN] waiting 15 seconds before subscribing")
    time.sleep(15)

    for req in subscriptions:
        print(f"[MAIN] subscribing: {req.symbol}.{req.exchange.value}")
        main_engine.subscribe(req, "CTP")
        time.sleep(1)

    print("[MAIN] waiting for ticks. Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[MAIN] closing")
    finally:
        main_engine.close()


if __name__ == "__main__":
    main()
