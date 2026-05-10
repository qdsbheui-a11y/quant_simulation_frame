from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from datetime import date
from typing import Any

from backtest.data import CsvDailyBarDataSource
from backtest.models import PositionState
from paper import SmallCapPaperConfig, build_smallcap_rebalance_plan
from simulation.models import OrderRequest, OrderType


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Submit a small-cap rebalance plan to the local simulation HTTP API.")
    parser.add_argument("--data", required=True, help="CSV file or directory containing daily stock snapshot bars.")
    parser.add_argument("--date", required=True, help="Trading date to rebalance, format YYYY-MM-DD.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--dry-run", action="store_true", help="Build and print orders without submitting them.")

    parser.add_argument("--top-n", type=int, default=30)
    parser.add_argument("--account-value", type=float, default=None, help="Override account equity. Defaults to API balance + unrealized PnL.")
    parser.add_argument("--cash-buffer", type=float, default=0.03)
    parser.add_argument("--lot-size", type=int, default=100)
    parser.add_argument("--min-listing-days", type=int, default=60)
    parser.add_argument("--min-turnover", type=float, default=20_000_000.0)
    parser.add_argument("--market-cap-field", choices=["float_market_cap", "total_market_cap"], default="float_market_cap")
    parser.add_argument("--price-field", choices=["open_price", "close_price"], default="close_price")
    parser.add_argument("--order-type", choices=["MARKET", "LIMIT"], default="MARKET")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    trading_date = date.fromisoformat(args.date)
    base_url = args.base_url.rstrip("/")

    data_source = CsvDailyBarDataSource(args.data)
    bars = data_source.bars_for_date(trading_date)
    if not bars:
        raise SystemExit(f"No bars found for date {trading_date} from {args.data}")

    snapshot = request_json("GET", f"{base_url}/simulation/snapshot")
    if not snapshot.get("ok"):
        raise SystemExit(f"simulation snapshot failed: {snapshot}")

    simulation = snapshot["data"]
    positions = parse_positions(simulation.get("positions", []))
    account = simulation.get("account", {})
    account_value = args.account_value
    if account_value is None:
        account_value = float(account.get("balance", 0.0)) + float(account.get("unrealized_pnl", 0.0))
    if account_value <= 0:
        raise SystemExit("account value must be positive. Use --account-value if the API account snapshot is empty.")

    config = SmallCapPaperConfig(
        top_n=args.top_n,
        account_value=account_value,
        cash_buffer=args.cash_buffer,
        lot_size=args.lot_size,
        min_listing_days=args.min_listing_days,
        min_turnover=args.min_turnover,
        market_cap_field=args.market_cap_field,
        order_type=OrderType(args.order_type),
        price_field=args.price_field,
    )
    plan = build_smallcap_rebalance_plan(trading_date, bars, positions, config)

    print("Small-cap paper rebalance plan")
    print(f"date:             {trading_date}")
    print(f"account value:    {account_value}")
    print(f"selected symbols: {len(plan.selected_symbols)}")
    print(f"sell orders:      {len(plan.sell_orders)}")
    print(f"buy orders:       {len(plan.buy_orders)}")
    print(f"total orders:     {len(plan.orders)}")
    print("selected:", ", ".join(plan.selected_symbols[:50]))

    for order in plan.orders:
        print(format_order(order))

    if args.dry_run:
        print("dry-run enabled; no orders submitted")
        return

    submitted: list[dict[str, Any]] = []
    for order in plan.orders:
        payload = order_to_payload(order)
        response = request_json("POST", f"{base_url}/simulation/orders", payload)
        submitted.append(response)
        print("submitted:", json.dumps(response.get("data", response), ensure_ascii=False))

    print(f"submitted orders: {len(submitted)}")


def parse_positions(items: list[dict[str, Any]]) -> dict[str, PositionState]:
    positions: dict[str, PositionState] = {}
    for item in items:
        vt_symbol = item["vt_symbol"]
        long_volume = int(float(item.get("long_volume", 0)))
        long_avg_price = float(item.get("long_avg_price", 0.0))
        if long_volume > 0:
            positions[vt_symbol] = PositionState(vt_symbol=vt_symbol, volume=long_volume, avg_price=long_avg_price)
    return positions


def order_to_payload(order: OrderRequest) -> dict[str, Any]:
    return {
        "vtSymbol": order.vt_symbol,
        "direction": order.direction.value,
        "offset": order.offset.value,
        "price": order.price,
        "volume": order.volume,
        "orderType": order.order_type.value,
    }


def format_order(order: OrderRequest) -> str:
    return (
        f"{order.direction.value:<5} {order.offset.value:<5} "
        f"{order.vt_symbol:<16} volume={order.volume:<8} price={order.price:<12} type={order.order_type.value}"
    )


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


if __name__ == "__main__":
    main()
