from __future__ import annotations

from math import sqrt

from .models import EquitySnapshot


TRADING_DAYS_PER_YEAR = 252


def calculate_metrics(equity_curve: list[EquitySnapshot]) -> dict[str, float]:
    if not equity_curve:
        return {
            "total_return": 0.0,
            "annual_return": 0.0,
            "annual_volatility": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "turnover": 0.0,
            "commission": 0.0,
            "tax": 0.0,
            "realized_pnl": 0.0,
            "final_equity": 0.0,
        }

    first = equity_curve[0]
    last = equity_curve[-1]
    initial_equity = first.total_equity
    final_equity = last.total_equity
    total_return = final_equity / initial_equity - 1 if initial_equity else 0.0

    periods = max(1, len(equity_curve) - 1)
    annual_return = (1 + total_return) ** (TRADING_DAYS_PER_YEAR / periods) - 1 if total_return > -1 else -1.0

    returns = []
    for previous, current in zip(equity_curve, equity_curve[1:]):
        if previous.total_equity:
            returns.append(current.total_equity / previous.total_equity - 1)

    annual_volatility = _annualized_volatility(returns)
    sharpe = annual_return / annual_volatility if annual_volatility else 0.0
    max_drawdown = _max_drawdown([item.total_equity for item in equity_curve])

    total_turnover = sum(item.turnover for item in equity_curve)
    total_commission = last.commission
    total_tax = last.tax
    realized_pnl = last.realized_pnl

    return {
        "total_return": total_return,
        "annual_return": annual_return,
        "annual_volatility": annual_volatility,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "turnover": total_turnover,
        "commission": total_commission,
        "tax": total_tax,
        "realized_pnl": realized_pnl,
        "final_equity": final_equity,
    }


def _annualized_volatility(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
    return sqrt(variance) * sqrt(TRADING_DAYS_PER_YEAR)


def _max_drawdown(values: list[float]) -> float:
    peak = 0.0
    max_dd = 0.0
    for value in values:
        peak = max(peak, value)
        if peak:
            max_dd = min(max_dd, value / peak - 1)
    return max_dd
