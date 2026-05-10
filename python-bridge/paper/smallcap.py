from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from backtest.models import DailyBar, PositionState
from backtest.strategy import BacktestContext, EqualWeightSmallCapStrategy
from simulation.models import Direction, Offset, OrderRequest, OrderType


@dataclass(slots=True)
class SmallCapPaperConfig:
    top_n: int = 30
    account_value: float = 1_000_000.0
    cash_buffer: float = 0.03
    lot_size: int = 100
    min_listing_days: int = 60
    min_turnover: float = 20_000_000.0
    market_cap_field: str = "float_market_cap"
    order_type: OrderType = OrderType.MARKET
    price_field: str = "close_price"


@dataclass(slots=True)
class SmallCapRebalancePlan:
    trading_date: date
    selected_symbols: list[str]
    sell_orders: list[OrderRequest] = field(default_factory=list)
    buy_orders: list[OrderRequest] = field(default_factory=list)

    @property
    def orders(self) -> list[OrderRequest]:
        return [*self.sell_orders, *self.buy_orders]


def build_smallcap_rebalance_plan(
    trading_date: date,
    bars: list[DailyBar],
    positions: dict[str, PositionState],
    config: SmallCapPaperConfig | None = None,
) -> SmallCapRebalancePlan:
    """Build sell-first paper-trading orders for small-cap rebalancing.

    The function is intentionally pure and does not submit orders. It reuses the
    backtest small-cap stock selector, then converts target equal weights into
    SimulationEngine OrderRequest objects.
    """

    cfg = config or SmallCapPaperConfig()
    strategy = EqualWeightSmallCapStrategy(
        top_n=cfg.top_n,
        min_listing_days=cfg.min_listing_days,
        min_turnover=cfg.min_turnover,
        market_cap_field=cfg.market_cap_field,
    )
    context = BacktestContext(
        date=trading_date,
        cash=0.0,
        total_equity=cfg.account_value,
        positions=positions,
    )
    targets = strategy.generate_targets(context, bars)
    selected_symbols = [target.vt_symbol for target in targets]
    target_set = set(selected_symbols)
    bar_map = {bar.vt_symbol: bar for bar in bars}
    target_weight = 1.0 / len(selected_symbols) if selected_symbols else 0.0
    target_value = cfg.account_value * (1 - cfg.cash_buffer) * target_weight if selected_symbols else 0.0

    sell_orders: list[OrderRequest] = []
    buy_orders: list[OrderRequest] = []

    # Sell removed symbols first.
    for vt_symbol, position in sorted(positions.items()):
        if position.volume <= 0:
            continue
        bar = bar_map.get(vt_symbol)
        if vt_symbol not in target_set:
            if bar is None or bar.is_suspended or bar.is_limit_down:
                continue
            sell_orders.append(_order(vt_symbol, Direction.SHORT, position.volume, _price(bar, cfg), cfg.order_type))

    # Rebalance selected symbols to equal weights.
    for vt_symbol in selected_symbols:
        bar = bar_map[vt_symbol]
        if bar.is_suspended:
            continue
        price = _price(bar, cfg)
        if price <= 0:
            continue
        current_volume = positions.get(vt_symbol, PositionState(vt_symbol=vt_symbol)).volume
        current_value = current_volume * price
        diff_value = target_value - current_value
        volume = _floor_to_lot(int(abs(diff_value) / price), cfg.lot_size)
        if volume <= 0:
            continue
        if diff_value > 0:
            if bar.is_limit_up:
                continue
            buy_orders.append(_order(vt_symbol, Direction.LONG, volume, price, cfg.order_type))
        else:
            if bar.is_limit_down:
                continue
            volume = min(volume, current_volume)
            if volume > 0:
                sell_orders.append(_order(vt_symbol, Direction.SHORT, volume, price, cfg.order_type))

    return SmallCapRebalancePlan(
        trading_date=trading_date,
        selected_symbols=selected_symbols,
        sell_orders=sell_orders,
        buy_orders=buy_orders,
    )


def _order(vt_symbol: str, direction: Direction, volume: int, price: float, order_type: OrderType) -> OrderRequest:
    return OrderRequest(
        vt_symbol=vt_symbol,
        direction=direction,
        offset=Offset.CLOSE if direction == Direction.SHORT else Offset.OPEN,
        price=max(price, 1e-12),
        volume=volume,
        order_type=order_type,
    )


def _price(bar: DailyBar, config: SmallCapPaperConfig) -> float:
    if config.price_field == "open_price":
        return bar.open_price
    if config.price_field == "close_price":
        return bar.close_price
    raise ValueError(f"unsupported price_field: {config.price_field}")


def _floor_to_lot(volume: int, lot_size: int) -> int:
    if lot_size <= 1:
        return max(0, volume)
    return max(0, volume // lot_size * lot_size)
