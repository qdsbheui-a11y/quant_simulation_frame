from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

BINANCE_SPOT_BASE_URL = "https://api.binance.com"
KLINES_PATH = "/api/v3/klines"
MAX_LIMIT = 1000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download Binance spot klines into backtest daily-bar CSV format.")
    parser.add_argument("--symbols", nargs="+", required=True, help="Binance spot symbols, e.g. BTCUSDT ETHUSDT.")
    parser.add_argument("--interval", default="1d", help="Binance kline interval, e.g. 1d, 4h, 1h.")
    parser.add_argument("--start", required=True, help="Start date, format YYYY-MM-DD.")
    parser.add_argument("--end", required=True, help="End date, format YYYY-MM-DD. Inclusive at date level.")
    parser.add_argument("--output", default="data/binance_bars", help="Output directory.")
    parser.add_argument("--sleep", type=float, default=0.2, help="Sleep seconds between API requests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    start_ms = _date_to_ms(date.fromisoformat(args.start))
    end_ms = _date_to_ms(date.fromisoformat(args.end)) + 24 * 60 * 60 * 1000 - 1

    for raw_symbol in args.symbols:
        symbol = raw_symbol.strip().upper()
        rows = download_symbol_klines(symbol, args.interval, start_ms, end_ms, args.sleep)
        output_file = output_dir / f"{symbol}_{args.interval}.csv"
        write_backtest_csv(output_file, symbol, rows)
        print(f"{symbol}: wrote {len(rows)} rows -> {output_file}")


def download_symbol_klines(symbol: str, interval: str, start_ms: int, end_ms: int, sleep_seconds: float) -> list[list[Any]]:
    all_rows: list[list[Any]] = []
    current_start = start_ms

    while current_start <= end_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": current_start,
            "endTime": end_ms,
            "limit": MAX_LIMIT,
        }
        rows = request_klines(params)
        if not rows:
            break

        all_rows.extend(rows)
        last_open_time = int(rows[-1][0])
        next_start = last_open_time + 1
        if next_start <= current_start:
            break
        current_start = next_start
        time.sleep(sleep_seconds)

        if len(rows) < MAX_LIMIT:
            break

    return all_rows


def request_klines(params: dict[str, Any]) -> list[list[Any]]:
    query = urllib.parse.urlencode(params)
    url = f"{BINANCE_SPOT_BASE_URL}{KLINES_PATH}?{query}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    if isinstance(data, dict) and "code" in data:
        raise RuntimeError(f"Binance API error: {data}")
    return data


def write_backtest_csv(path: Path, symbol: str, rows: list[list[Any]]) -> None:
    fieldnames = [
        "date",
        "vt_symbol",
        "symbol",
        "exchange",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        "turnover",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            open_time = int(row[0])
            writer.writerow(
                {
                    "date": _ms_to_utc_date(open_time).isoformat(),
                    "vt_symbol": f"{symbol}.BINANCE",
                    "symbol": symbol,
                    "exchange": "BINANCE",
                    "open_price": row[1],
                    "high_price": row[2],
                    "low_price": row[3],
                    "close_price": row[4],
                    "volume": row[5],
                    "turnover": row[7],
                }
            )


def _date_to_ms(value: date) -> int:
    dt = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _ms_to_utc_date(value: int) -> date:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date()


if __name__ == "__main__":
    main()
