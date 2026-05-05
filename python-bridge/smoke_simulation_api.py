"""Smoke test for the local paper-trading simulation HTTP API.

Run the bridge first from python-bridge:

    python bridge_server.py

Then in another shell:

    python smoke_simulation_api.py

The script uses only Python's standard library. It starts mock ticks, submits a
marketable open order, submits a marketable close order, and verifies that the
simulation generated trades and updated account/position state.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:8765"
DEFAULT_SYMBOL = "au2606.SHFE"


def request_json(method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {method} {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot connect to {url}: {exc.reason}") from exc


def get(base_url: str, path: str) -> dict[str, Any]:
    return request_json("GET", f"{base_url}{path}")


def post(base_url: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return request_json("POST", f"{base_url}{path}", payload or {})


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--volume", type=float, default=1.0)
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")

    print(f"[1/7] health: {base_url}/health")
    health = get(base_url, "/health")
    require(health.get("ok") is True, "bridge health check failed")

    print("[2/7] reset simulation account")
    post(
        base_url,
        "/simulation/reset",
        {
            "initialBalance": 1_000_000,
            "commissionRate": 0.0001,
            "slippage": 0,
        },
    )

    print(f"[3/7] start mock ticks for {args.symbol}")
    post(base_url, "/mock/start", {"symbols": [args.symbol], "intervalSeconds": args.interval})
    time.sleep(max(args.interval * 2, 1.0))

    health = get(base_url, "/health")
    last_tick = health.get("lastTick")
    require(last_tick and last_tick.get("vt_symbol") == args.symbol, "mock tick was not received")
    print(f"      last tick: {last_tick.get('vt_symbol')} last={last_tick.get('last_price')}")

    print("[4/7] submit marketable LONG OPEN limit order")
    open_order_resp = post(
        base_url,
        "/simulation/orders",
        {
            "vtSymbol": args.symbol,
            "direction": "LONG",
            "offset": "OPEN",
            "orderType": "LIMIT",
            "price": 1_000_000_000,
            "volume": args.volume,
        },
    )
    open_order = open_order_resp.get("data", {})
    print(f"      open order: {open_order.get('order_id')} status={open_order.get('status')}")
    require(open_order.get("status") == "ALL_TRADED", "open order was not fully traded")

    print("[5/7] submit marketable SHORT CLOSE limit order")
    close_order_resp = post(
        base_url,
        "/simulation/orders",
        {
            "vtSymbol": args.symbol,
            "direction": "SHORT",
            "offset": "CLOSE",
            "orderType": "LIMIT",
            "price": 0.01,
            "volume": args.volume,
        },
    )
    close_order = close_order_resp.get("data", {})
    print(f"      close order: {close_order.get('order_id')} status={close_order.get('status')}")
    require(close_order.get("status") == "ALL_TRADED", "close order was not fully traded")

    print("[6/7] verify snapshot")
    snapshot = get(base_url, "/simulation/snapshot").get("data", {})
    account = snapshot.get("account", {})
    positions = snapshot.get("positions", [])
    trades = snapshot.get("trades", [])

    require(len(trades) >= 2, "expected at least two trades")
    position = next((item for item in positions if item.get("vt_symbol") == args.symbol), None)
    if position:
        require(position.get("long_volume", 0) == 0, "long position should be closed")

    print("[7/7] stop mock ticks")
    post(base_url, "/mock/stop")

    print("\nSmoke test passed.")
    print(f"Balance: {account.get('balance')}")
    print(f"Realized PnL: {account.get('realized_pnl')}")
    print(f"Commission: {account.get('commission')}")
    print(f"Trades: {len(trades)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nSmoke test failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
