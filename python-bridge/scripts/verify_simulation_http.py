from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from typing import Any


def request_json(method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        raise RuntimeError(f"{method} {url} failed: HTTP {exc.code}: {body}") from exc


def assert_ok(response: dict[str, Any], message: str) -> None:
    if not response.get("ok"):
        raise AssertionError(f"{message} failed: {response}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify local simulation HTTP order flow.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--symbol", default="au2606.SHFE")
    parser.add_argument("--wait-seconds", type=float, default=2.0)
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")

    health = request_json("GET", f"{base_url}/health")
    assert_ok(health, "health")
    print("health ok")

    reset = request_json(
        "POST",
        f"{base_url}/simulation/reset",
        {"initialBalance": 1_000_000, "commissionRate": 0.0001, "slippage": 0.0},
    )
    assert_ok(reset, "simulation reset")
    print("simulation reset ok")

    mock = request_json(
        "POST",
        f"{base_url}/mock/start",
        {"symbols": [args.symbol], "intervalSeconds": 0.5},
    )
    assert_ok(mock, "mock start")
    print("mock source started")

    time.sleep(args.wait_seconds)

    snapshot = request_json("GET", f"{base_url}/simulation/snapshot")
    assert_ok(snapshot, "snapshot")
    last_ticks = snapshot["data"].get("lastTicks", [])
    if not last_ticks:
        raise AssertionError("expected at least one mock tick before submitting order")

    tick = next((item for item in last_ticks if item["vt_symbol"] == args.symbol), last_ticks[0])
    ask = float(tick["ask_price_1"])
    bid = float(tick["bid_price_1"])
    print(f"latest tick bid={bid} ask={ask}")

    open_order = request_json(
        "POST",
        f"{base_url}/simulation/orders",
        {
            "vtSymbol": args.symbol,
            "direction": "LONG",
            "offset": "OPEN",
            "price": ask,
            "volume": 1,
            "orderType": "LIMIT",
        },
    )
    assert_ok(open_order, "open order")
    if open_order["data"]["status"] != "ALL_TRADED":
        raise AssertionError(f"expected open order ALL_TRADED, got {open_order['data']}")
    print("open order matched")

    close_order = request_json(
        "POST",
        f"{base_url}/simulation/orders",
        {
            "vtSymbol": args.symbol,
            "direction": "SHORT",
            "offset": "CLOSE",
            "price": bid,
            "volume": 1,
            "orderType": "LIMIT",
        },
    )
    assert_ok(close_order, "close order")
    if close_order["data"]["status"] != "ALL_TRADED":
        raise AssertionError(f"expected close order ALL_TRADED, got {close_order['data']}")
    print("close order matched")

    positions = request_json("GET", f"{base_url}/simulation/positions")
    assert_ok(positions, "positions")
    trades = request_json("GET", f"{base_url}/simulation/trades")
    assert_ok(trades, "trades")
    account = request_json("GET", f"{base_url}/simulation/account")
    assert_ok(account, "account")

    if len(trades["data"]) < 2:
        raise AssertionError(f"expected at least 2 trades, got {trades['data']}")

    print("positions:", json.dumps(positions["data"], ensure_ascii=False))
    print("account:", json.dumps(account["data"], ensure_ascii=False))
    print("simulation HTTP verification passed")


if __name__ == "__main__":
    main()
