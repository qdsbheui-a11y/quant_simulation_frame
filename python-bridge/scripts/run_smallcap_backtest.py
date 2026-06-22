from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest import BacktestConfig, BacktestRunner, CsvDailyBarDataSource, EqualWeightSmallCapStrategy, write_html_report


REQUIRED_COLUMNS = ["date", "vt_symbol", "open_price", "high_price", "low_price", "close_price"]
OPTIONAL_SMALL_CAP_COLUMNS = [
    "float_market_cap",
    "total_market_cap",
    "turnover",
    "is_st",
    "is_suspended",
    "listing_days",
    "limit_up",
    "limit_down",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an equal-weight small-cap daily backtest.")
    parser.add_argument("--data", required=True, help="CSV file or directory containing daily bar CSV files.")
    parser.add_argument("--output", default="backtest_output", help="Directory for result CSV/JSON/HTML files.")
    parser.add_argument("--start", default=None, help="Start date, format YYYY-MM-DD.")
    parser.add_argument("--end", default=None, help="End date, format YYYY-MM-DD.")

    parser.add_argument("--top-n", type=int, default=30)
    parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    parser.add_argument("--rebalance", choices=["daily", "weekly", "monthly"], default="monthly")
    parser.add_argument("--price-field", choices=["open_price", "close_price"], default="open_price")

    parser.add_argument("--commission-rate", type=float, default=0.0003)
    parser.add_argument("--min-commission", type=float, default=5.0)
    parser.add_argument("--stamp-tax-rate", type=float, default=0.0005)
    parser.add_argument("--slippage-bps", type=float, default=0.0)
    parser.add_argument("--cash-buffer", type=float, default=0.03)
    parser.add_argument("--lot-size", type=int, default=100)

    parser.add_argument("--min-listing-days", type=int, default=60)
    parser.add_argument("--min-turnover", type=float, default=20_000_000.0)
    parser.add_argument("--market-cap-field", choices=["float_market_cap", "total_market_cap"], default="float_market_cap")
    parser.add_argument("--include-limit-up", action="store_true", help="Allow buying stocks closed at limit-up.")
    parser.add_argument("--include-limit-down", action="store_true", help="Allow selling/holding candidates closed at limit-down.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    _validate_data_path(Path(args.data))

    start_date = _parse_date(args.start)
    end_date = _parse_date(args.end)

    data_source = CsvDailyBarDataSource(args.data)
    strategy = EqualWeightSmallCapStrategy(
        top_n=args.top_n,
        min_listing_days=args.min_listing_days,
        min_turnover=args.min_turnover,
        market_cap_field=args.market_cap_field,
        exclude_limit_up=not args.include_limit_up,
        exclude_limit_down=not args.include_limit_down,
    )
    config = BacktestConfig(
        initial_cash=args.initial_cash,
        commission_rate=args.commission_rate,
        min_commission=args.min_commission,
        stamp_tax_rate=args.stamp_tax_rate,
        slippage_bps=args.slippage_bps,
        lot_size=args.lot_size,
        cash_buffer=args.cash_buffer,
        price_field=args.price_field,
        rebalance_frequency=args.rebalance,
    )

    runner = BacktestRunner(data_source=data_source, strategy=strategy, config=config)
    result = runner.run(start_date=start_date, end_date=end_date)

    if not result.equity_curve:
        raise SystemExit(
            "No bars were loaded for the requested date range. "
            "Check --data, --start, --end, and CSV date values."
        )

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    _write_equity_curve(output_dir / "equity_curve.csv", result.equity_curve)
    _write_trades(output_dir / "trades.csv", result.trades)
    _write_positions(output_dir / "final_positions.csv", result.final_positions)
    _write_json(output_dir / "metrics.json", result.metrics)
    report_path = output_dir / "report.html"
    write_html_report(
        report_path,
        result,
        title="Small-cap Strategy Tester Report",
        parameters={
            "data": args.data,
            "start": args.start,
            "end": args.end,
            "strategy": "EqualWeightSmallCapStrategy",
            "top_n": args.top_n,
            "initial_cash": args.initial_cash,
            "rebalance": args.rebalance,
            "price_field": args.price_field,
            "commission_rate": args.commission_rate,
            "min_commission": args.min_commission,
            "stamp_tax_rate": args.stamp_tax_rate,
            "slippage_bps": args.slippage_bps,
            "cash_buffer": args.cash_buffer,
            "lot_size": args.lot_size,
            "min_listing_days": args.min_listing_days,
            "min_turnover": args.min_turnover,
            "market_cap_field": args.market_cap_field,
            "include_limit_up": args.include_limit_up,
            "include_limit_down": args.include_limit_down,
        },
    )

    print("Backtest completed")
    print(f"equity_curve: {output_dir / 'equity_curve.csv'}")
    print(f"trades:       {output_dir / 'trades.csv'}")
    print(f"positions:    {output_dir / 'final_positions.csv'}")
    print(f"metrics:      {output_dir / 'metrics.json'}")
    print(f"report:       {report_path}")
    print("")
    print("Metrics")
    for key, value in result.metrics.items():
        print(f"{key}: {_format_metric(value)}")


def _validate_data_path(path: Path) -> None:
    if not path.exists():
        example_columns = ",".join(REQUIRED_COLUMNS + OPTIONAL_SMALL_CAP_COLUMNS)
        raise SystemExit(
            f"Data path does not exist: {path}\n"
            "Create the directory or pass an existing CSV file/directory with --data.\n"
            "Required columns: " + ", ".join(REQUIRED_COLUMNS) + "\n"
            "Recommended small-cap columns: " + ", ".join(OPTIONAL_SMALL_CAP_COLUMNS) + "\n"
            "CSV header example:\n"
            f"{example_columns}"
        )

    if path.is_dir() and not list(path.glob("*.csv")):
        raise SystemExit(f"Data directory contains no CSV files: {path}")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _write_equity_curve(path: Path, rows: list[Any]) -> None:
    fieldnames = ["date", "cash", "market_value", "total_equity", "commission", "tax", "turnover", "realized_pnl"]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for item in rows:
            row = asdict(item)
            row["date"] = row["date"].isoformat()
            writer.writerow(row)


def _write_trades(path: Path, rows: list[Any]) -> None:
    fieldnames = [
        "date",
        "vt_symbol",
        "side",
        "price",
        "volume",
        "amount",
        "commission",
        "tax",
        "cash_delta",
        "realized_pnl",
        "reason",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for item in rows:
            row = asdict(item)
            row["date"] = row["date"].isoformat()
            writer.writerow(row)


def _write_positions(path: Path, positions: dict[str, Any]) -> None:
    fieldnames = ["vt_symbol", "volume", "avg_price"]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for item in positions.values():
            writer.writerow(asdict(item))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def _format_metric(value: float) -> str:
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


if __name__ == "__main__":
    main()
