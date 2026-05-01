from __future__ import annotations

import argparse
import asyncio

from .binance_spot import BinanceSpotGateway
from .demo_strategy import DemoBuyOnceStrategy
from .sim_broker import SimBroker
from .tushare_realtime import TushareRealtimeGateway


def parse_symbols(raw: str | None, fallback: list[str]) -> list[str]:
    if not raw:
        return fallback
    return [item.strip() for item in raw.split(",") if item.strip()]


async def run_loop(label: str, gateway, strategy: DemoBuyOnceStrategy, broker: SimBroker, max_ticks: int | None) -> None:
    seen = 0
    async for tick in gateway.ticks():
        print(f"[{label}] tick {tick.symbol} bid={tick.bid_price} ask={tick.ask_price} last={tick.last_price}")
        await strategy.on_tick(tick)
        for fill in broker.on_tick(tick):
            print(f"[{label}] fill {fill}")
            print(f"[{label}] account {broker.snapshot()}")
        seen += 1
        if max_ticks is not None and seen >= max_ticks:
            await gateway.close()
            return


async def amain() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["binance", "tushare"], default="binance")
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--volume", type=float, default=None)
    parser.add_argument("--interval", type=float, default=3.0)
    parser.add_argument("--max-ticks", type=int, default=10)
    args = parser.parse_args()

    max_ticks = None if args.max_ticks == 0 else args.max_ticks
    broker = SimBroker(initial_cash=1_000_000.0)

    if args.source == "binance":
        gateway = BinanceSpotGateway(parse_symbols(args.symbols, ["btcusdt"]))
        volume = args.volume if args.volume is not None else 0.001
    else:
        gateway = TushareRealtimeGateway(parse_symbols(args.symbols, ["000001.SZ"]), interval=args.interval)
        volume = args.volume if args.volume is not None else 100

    strategy = DemoBuyOnceStrategy(broker=broker, volume=volume)
    await run_loop(args.source, gateway, strategy, broker, max_ticks)


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
