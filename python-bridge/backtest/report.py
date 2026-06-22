from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from html import escape
from math import isfinite
from pathlib import Path
from typing import Any

from .models import BacktestResult, BacktestTrade, EquitySnapshot, PositionState


Number = int | float


def write_html_report(
    path: str | Path,
    result: BacktestResult,
    *,
    title: str = "Strategy Tester Report",
    parameters: dict[str, Any] | None = None,
) -> None:
    """Write an MT-style self-contained HTML report.

    The report intentionally uses only static HTML/CSS/SVG so it can be opened
    directly in a browser or archived with the CSV/JSON result files.
    """

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    parameters = parameters or {}
    stats = calculate_mt_style_statistics(result)

    html = "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{_e(title)}</title>",
            "<style>",
            _CSS,
            "</style>",
            "</head>",
            "<body>",
            '<main class="report">',
            _header(title, result),
            _section("Test Parameters", _key_value_table(parameters)),
            _section("Result Summary", _metric_grid(_summary_metrics(stats))),
            _section("MT-style Trade Statistics", _key_value_table(_trade_statistics(stats))),
            _section("Equity / Balance Chart", _equity_svg(result.equity_curve, stats)),
            _section("Equity Curve", _equity_table(result.equity_curve)),
            _section("Trades", _trades_table(result.trades)),
            _section("Final Positions", _positions_table(result.final_positions)),
            "</main>",
            "</body>",
            "</html>",
        ]
    )
    output_path.write_text(html, encoding="utf-8")


def calculate_mt_style_statistics(result: BacktestResult) -> dict[str, Any]:
    equity_curve = result.equity_curve
    trades = result.trades
    initial_deposit = equity_curve[0].total_equity if equity_curve else 0.0
    final_equity = equity_curve[-1].total_equity if equity_curve else 0.0
    net_profit = final_equity - initial_deposit

    close_pnls = [trade.realized_pnl - trade.commission - trade.tax for trade in trades if trade.realized_pnl != 0]
    positive_pnls = [value for value in close_pnls if value > 0]
    negative_pnls = [value for value in close_pnls if value < 0]
    gross_profit = sum(positive_pnls)
    gross_loss = sum(negative_pnls)
    profit_factor = gross_profit / abs(gross_loss) if gross_loss else (float("inf") if gross_profit > 0 else 0.0)

    total_trades = len(trades)
    buy_trades = sum(1 for trade in trades if trade.side == "BUY")
    sell_trades = sum(1 for trade in trades if trade.side == "SELL")
    winning_trades = len(positive_pnls)
    losing_trades = len(negative_pnls)
    win_rate = winning_trades / (winning_trades + losing_trades) if winning_trades + losing_trades else 0.0
    expected_payoff = net_profit / total_trades if total_trades else 0.0

    max_drawdown_money, max_drawdown_percent = _max_drawdown_money_percent(equity_curve)
    min_equity = min((item.total_equity for item in equity_curve), default=initial_deposit)
    absolute_drawdown = max(0.0, initial_deposit - min_equity)

    largest_profit = max(positive_pnls, default=0.0)
    largest_loss = min(negative_pnls, default=0.0)
    average_profit = gross_profit / winning_trades if winning_trades else 0.0
    average_loss = gross_loss / losing_trades if losing_trades else 0.0
    max_consecutive_wins, max_consecutive_win_profit = _max_consecutive(close_pnls, positive=True)
    max_consecutive_losses, max_consecutive_loss_value = _max_consecutive(close_pnls, positive=False)

    return {
        "initial_deposit": initial_deposit,
        "final_equity": final_equity,
        "net_profit": net_profit,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": profit_factor,
        "expected_payoff": expected_payoff,
        "absolute_drawdown": absolute_drawdown,
        "max_drawdown_money": max_drawdown_money,
        "max_drawdown_percent": max_drawdown_percent,
        "relative_drawdown_percent": max_drawdown_percent,
        "total_trades": total_trades,
        "buy_trades": buy_trades,
        "sell_trades": sell_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": win_rate,
        "largest_profit_trade": largest_profit,
        "largest_loss_trade": largest_loss,
        "average_profit_trade": average_profit,
        "average_loss_trade": average_loss,
        "max_consecutive_wins": max_consecutive_wins,
        "max_consecutive_win_profit": max_consecutive_win_profit,
        "max_consecutive_losses": max_consecutive_losses,
        "max_consecutive_loss_value": max_consecutive_loss_value,
        "metrics": result.metrics,
    }


def _header(title: str, result: BacktestResult) -> str:
    started = result.equity_curve[0].date.isoformat() if result.equity_curve else "-"
    ended = result.equity_curve[-1].date.isoformat() if result.equity_curve else "-"
    generated = datetime.now().isoformat(timespec="seconds")
    return (
        '<header class="report-header">'
        f'<div><h1>{_e(title)}</h1><p>Period: {_e(started)} — {_e(ended)}</p></div>'
        f'<div class="generated">Generated: {_e(generated)}</div>'
        "</header>"
    )


def _section(title: str, body: str) -> str:
    return f'<section class="section"><h2>{_e(title)}</h2>{body}</section>'


def _summary_metrics(stats: dict[str, Any]) -> list[tuple[str, str]]:
    metrics = stats.get("metrics", {})
    return [
        ("Initial Deposit", _fmt_money(stats["initial_deposit"])),
        ("Final Equity", _fmt_money(stats["final_equity"])),
        ("Net Profit", _fmt_money(stats["net_profit"])),
        ("Total Return", _fmt_percent(metrics.get("total_return", 0.0))),
        ("Annual Return", _fmt_percent(metrics.get("annual_return", 0.0))),
        ("Max Drawdown", f"{_fmt_money(stats['max_drawdown_money'])} ({_fmt_percent(stats['max_drawdown_percent'])})"),
        ("Sharpe Ratio", _fmt_number(metrics.get("sharpe", 0.0), 4)),
        ("Profit Factor", _fmt_number(stats["profit_factor"], 4)),
        ("Total Trades", str(stats["total_trades"])),
        ("Win Rate", _fmt_percent(stats["win_rate"])),
        ("Commission", _fmt_money(metrics.get("commission", 0.0))),
        ("Tax", _fmt_money(metrics.get("tax", 0.0))),
    ]


def _trade_statistics(stats: dict[str, Any]) -> dict[str, Any]:
    metrics = stats.get("metrics", {})
    return {
        "Initial deposit": _fmt_money(stats["initial_deposit"]),
        "Total net profit": _fmt_money(stats["net_profit"]),
        "Gross profit": _fmt_money(stats["gross_profit"]),
        "Gross loss": _fmt_money(stats["gross_loss"]),
        "Profit factor": _fmt_number(stats["profit_factor"], 4),
        "Expected payoff": _fmt_money(stats["expected_payoff"]),
        "Absolute drawdown": _fmt_money(stats["absolute_drawdown"]),
        "Maximal drawdown": f"{_fmt_money(stats['max_drawdown_money'])} ({_fmt_percent(stats['max_drawdown_percent'])})",
        "Relative drawdown": _fmt_percent(stats["relative_drawdown_percent"]),
        "Total trades": stats["total_trades"],
        "Buy trades": stats["buy_trades"],
        "Sell trades": stats["sell_trades"],
        "Winning trades": f"{stats['winning_trades']} ({_fmt_percent(stats['win_rate'])})",
        "Losing trades": stats["losing_trades"],
        "Largest profit trade": _fmt_money(stats["largest_profit_trade"]),
        "Largest loss trade": _fmt_money(stats["largest_loss_trade"]),
        "Average profit trade": _fmt_money(stats["average_profit_trade"]),
        "Average loss trade": _fmt_money(stats["average_loss_trade"]),
        "Maximum consecutive wins": f"{stats['max_consecutive_wins']} ({_fmt_money(stats['max_consecutive_win_profit'])})",
        "Maximum consecutive losses": f"{stats['max_consecutive_losses']} ({_fmt_money(stats['max_consecutive_loss_value'])})",
        "Annual volatility": _fmt_percent(metrics.get("annual_volatility", 0.0)),
        "Turnover": _fmt_money(metrics.get("turnover", 0.0)),
    }


def _metric_grid(items: list[tuple[str, str]]) -> str:
    cards = []
    for label, value in items:
        tone = " positive" if label in {"Net Profit", "Total Return", "Annual Return"} and not str(value).startswith("-") else ""
        cards.append(f'<div class="metric{tone}"><span>{_e(label)}</span><strong>{_e(value)}</strong></div>')
    return '<div class="metric-grid">' + "".join(cards) + "</div>"


def _key_value_table(values: dict[str, Any]) -> str:
    if not values:
        return '<p class="empty">No data.</p>'
    rows = []
    for key, value in values.items():
        rows.append(f"<tr><th>{_e(str(key))}</th><td>{_e(_stringify(value))}</td></tr>")
    return '<table class="kv"><tbody>' + "".join(rows) + "</tbody></table>"


def _equity_svg(equity_curve: list[EquitySnapshot], stats: dict[str, Any]) -> str:
    if not equity_curve:
        return '<p class="empty">No equity data.</p>'

    width = 980
    height = 320
    margin_left = 58
    margin_right = 20
    margin_top = 20
    margin_bottom = 42

    equity_values = [item.total_equity for item in equity_curve]
    initial = stats.get("initial_deposit", equity_values[0])
    balance_values = [initial + item.realized_pnl - item.commission - item.tax for item in equity_curve]
    all_values = equity_values + balance_values
    y_min = min(all_values)
    y_max = max(all_values)
    if y_min == y_max:
        y_min -= 1
        y_max += 1

    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    def point(index: int, value: float) -> tuple[float, float]:
        x = margin_left + (plot_w * index / max(1, len(equity_curve) - 1))
        y = margin_top + plot_h - ((value - y_min) / (y_max - y_min) * plot_h)
        return x, y

    equity_points = " ".join(f"{x:.2f},{y:.2f}" for x, y in (point(i, v) for i, v in enumerate(equity_values)))
    balance_points = " ".join(f"{x:.2f},{y:.2f}" for x, y in (point(i, v) for i, v in enumerate(balance_values)))

    y_ticks = []
    for idx in range(5):
        value = y_min + (y_max - y_min) * idx / 4
        _x, y = point(0, value)
        y_ticks.append(
            f'<line class="grid" x1="{margin_left}" y1="{y:.2f}" x2="{width - margin_right}" y2="{y:.2f}" />'
            f'<text class="axis" x="8" y="{y + 4:.2f}">{_e(_fmt_number(value, 0))}</text>'
        )

    first_date = equity_curve[0].date.isoformat()
    last_date = equity_curve[-1].date.isoformat()
    return f'''
<div class="chart-wrap">
<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="Equity and balance chart">
  <rect class="plot-bg" x="{margin_left}" y="{margin_top}" width="{plot_w}" height="{plot_h}" />
  {''.join(y_ticks)}
  <polyline class="line balance" points="{balance_points}" />
  <polyline class="line equity" points="{equity_points}" />
  <text class="axis" x="{margin_left}" y="{height - 14}">{_e(first_date)}</text>
  <text class="axis right" x="{width - margin_right}" y="{height - 14}">{_e(last_date)}</text>
</svg>
<div class="legend"><span class="legend-equity">Equity</span><span class="legend-balance">Balance</span></div>
</div>
'''


def _equity_table(rows: list[EquitySnapshot]) -> str:
    if not rows:
        return '<p class="empty">No data.</p>'
    header = "<tr><th>Date</th><th>Cash</th><th>Market Value</th><th>Total Equity</th><th>Commission</th><th>Tax</th><th>Turnover</th><th>Realized PnL</th></tr>"
    body = []
    for item in rows:
        body.append(
            "<tr>"
            f"<td>{_e(item.date.isoformat())}</td>"
            f"<td class='num'>{_fmt_money(item.cash)}</td>"
            f"<td class='num'>{_fmt_money(item.market_value)}</td>"
            f"<td class='num'>{_fmt_money(item.total_equity)}</td>"
            f"<td class='num'>{_fmt_money(item.commission)}</td>"
            f"<td class='num'>{_fmt_money(item.tax)}</td>"
            f"<td class='num'>{_fmt_money(item.turnover)}</td>"
            f"<td class='num'>{_fmt_money(item.realized_pnl)}</td>"
            "</tr>"
        )
    return '<div class="table-scroll"><table>' + header + "".join(body) + "</table></div>"


def _trades_table(rows: list[BacktestTrade]) -> str:
    if not rows:
        return '<p class="empty">No trades.</p>'
    header = "<tr><th>#</th><th>Date</th><th>Symbol</th><th>Side</th><th>Price</th><th>Volume</th><th>Amount</th><th>Commission</th><th>Tax</th><th>Cash Delta</th><th>Realized PnL</th><th>Reason</th></tr>"
    body = []
    for index, trade in enumerate(rows, start=1):
        pnl_class = "pos" if trade.realized_pnl > 0 else "neg" if trade.realized_pnl < 0 else ""
        body.append(
            "<tr>"
            f"<td class='num'>{index}</td>"
            f"<td>{_e(trade.date.isoformat())}</td>"
            f"<td>{_e(trade.vt_symbol)}</td>"
            f"<td>{_e(trade.side)}</td>"
            f"<td class='num'>{_fmt_number(trade.price, 4)}</td>"
            f"<td class='num'>{_fmt_number(trade.volume, 4)}</td>"
            f"<td class='num'>{_fmt_money(trade.amount)}</td>"
            f"<td class='num'>{_fmt_money(trade.commission)}</td>"
            f"<td class='num'>{_fmt_money(trade.tax)}</td>"
            f"<td class='num'>{_fmt_money(trade.cash_delta)}</td>"
            f"<td class='num {pnl_class}'>{_fmt_money(trade.realized_pnl)}</td>"
            f"<td>{_e(trade.reason)}</td>"
            "</tr>"
        )
    return '<div class="table-scroll"><table>' + header + "".join(body) + "</table></div>"


def _positions_table(positions: dict[str, PositionState]) -> str:
    if not positions:
        return '<p class="empty">No final positions.</p>'
    header = "<tr><th>Symbol</th><th>Volume</th><th>Average Price</th></tr>"
    body = []
    for symbol, position in sorted(positions.items()):
        body.append(
            "<tr>"
            f"<td>{_e(symbol)}</td>"
            f"<td class='num'>{_fmt_number(position.volume, 4)}</td>"
            f"<td class='num'>{_fmt_number(position.avg_price, 4)}</td>"
            "</tr>"
        )
    return '<div class="table-scroll"><table>' + header + "".join(body) + "</table></div>"


def _max_drawdown_money_percent(equity_curve: list[EquitySnapshot]) -> tuple[float, float]:
    peak = 0.0
    max_dd_money = 0.0
    max_dd_percent = 0.0
    for item in equity_curve:
        equity = item.total_equity
        if equity > peak:
            peak = equity
        if peak <= 0:
            continue
        dd_money = peak - equity
        dd_percent = dd_money / peak
        if dd_money > max_dd_money:
            max_dd_money = dd_money
            max_dd_percent = dd_percent
    return max_dd_money, max_dd_percent


def _max_consecutive(values: list[float], *, positive: bool) -> tuple[int, float]:
    best_count = 0
    best_sum = 0.0
    current_count = 0
    current_sum = 0.0
    for value in values:
        matched = value > 0 if positive else value < 0
        if matched:
            current_count += 1
            current_sum += value
            if current_count > best_count:
                best_count = current_count
                best_sum = current_sum
        else:
            current_count = 0
            current_sum = 0.0
    return best_count, best_sum


def _fmt_money(value: Any) -> str:
    if isinstance(value, (int, float)):
        return _fmt_number(float(value), 2)
    return _stringify(value)


def _fmt_percent(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value * 100:.2f}%"
    return _stringify(value)


def _fmt_number(value: Any, digits: int = 2) -> str:
    if isinstance(value, (int, float)):
        if not isfinite(float(value)):
            return "∞" if value > 0 else "-∞"
        return f"{float(value):,.{digits}f}"
    return _stringify(value)


def _stringify(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{key}={_stringify(val)}" for key, val in value.items())
    if isinstance(value, (list, tuple, set)):
        return ", ".join(_stringify(item) for item in value)
    return str(value)


def _e(value: str) -> str:
    return escape(value, quote=True)


_CSS = r'''
:root {
  --bg: #f3f4f6;
  --paper: #ffffff;
  --ink: #111827;
  --muted: #6b7280;
  --line: #d1d5db;
  --soft: #eef2f7;
  --blue: #1d4ed8;
  --green: #047857;
  --red: #b91c1c;
  --amber: #92400e;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); font-family: Tahoma, Arial, sans-serif; font-size: 13px; }
.report { max-width: 1180px; margin: 18px auto; padding: 0 14px 30px; }
.report-header { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; background: linear-gradient(180deg, #ffffff, #eef2ff); border: 1px solid var(--line); padding: 18px 20px; }
h1 { margin: 0 0 6px; font-size: 22px; }
h2 { margin: 0 0 10px; font-size: 15px; border-bottom: 1px solid var(--line); padding-bottom: 7px; }
p { margin: 0; color: var(--muted); }
.generated { color: var(--muted); white-space: nowrap; }
.section { margin-top: 14px; background: var(--paper); border: 1px solid var(--line); padding: 14px; }
.metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.metric { border: 1px solid var(--line); background: #fafafa; padding: 10px; min-height: 62px; }
.metric span { display: block; color: var(--muted); margin-bottom: 8px; }
.metric strong { font-size: 17px; }
.metric.positive strong { color: var(--green); }
table { width: 100%; border-collapse: collapse; }
th, td { border: 1px solid var(--line); padding: 6px 8px; vertical-align: top; }
th { background: var(--soft); text-align: left; font-weight: 600; }
.kv th { width: 36%; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.pos { color: var(--green); }
.neg { color: var(--red); }
.table-scroll { overflow-x: auto; }
.empty { padding: 8px 0; }
.chart-wrap { width: 100%; overflow-x: auto; }
.chart { min-width: 760px; width: 100%; height: 330px; background: #ffffff; border: 1px solid var(--line); }
.plot-bg { fill: #fbfdff; stroke: var(--line); }
.grid { stroke: #e5e7eb; stroke-width: 1; }
.axis { fill: var(--muted); font-size: 12px; }
.axis.right { text-anchor: end; }
.line { fill: none; stroke-width: 2.2; }
.line.equity { stroke: var(--blue); }
.line.balance { stroke: var(--green); stroke-dasharray: 5 4; }
.legend { display: flex; gap: 18px; margin-top: 8px; color: var(--muted); }
.legend span::before { content: ''; display: inline-block; width: 22px; height: 3px; margin-right: 6px; vertical-align: middle; }
.legend-equity::before { background: var(--blue); }
.legend-balance::before { background: var(--green); }
@media (max-width: 900px) {
  .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .report-header { flex-direction: column; }
}
@media print {
  body { background: #fff; }
  .report { max-width: none; margin: 0; }
  .section, .report-header { break-inside: avoid; }
}
'''
