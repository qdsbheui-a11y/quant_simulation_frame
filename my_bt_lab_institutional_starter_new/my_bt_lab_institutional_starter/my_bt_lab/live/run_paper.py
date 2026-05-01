from __future__ import annotations

import argparse
import asyncio

from .akshare_realtime import AkShareRealtimeGateway
from .binance_spot import BinanceSpotGateway
from .demo_strategy import DemoBuyOnceStrategy
from .efinance_realtime import EFinanceRealtimeGateway
from .mootdx_realtime import MootdxRealtimeGateway
from .recorder import JsonlTickRecorder
from .replay_gateway import ReplayGateway
from .sim_broker import SimBroker
from .tushare_realtime import TushareRealtimeGateway


def parse_symbols(raw: str | None, fallback: list[str]) -> list[str]:
    if not raw:
        return fallback
    return [item.strip() for item in raw.split(",") if item.strip()]


async def run_loop(
    label: str,
    gateway,
    strategy: DemoBuyOnceStrategy,
    broker: SimBroker,
    max_ticks: int | None,
    record_path: str | None = None,
) -> None:
    recorder = JsonlTickRecorder(record_path) if record_path else None
    seen = 0
    try:
        async for tick in gateway.ticks():
            if recorder is not None:
                recorder.write(tick)
            print(f"[{label}] tick {tick.symbol} bid={tick.bid_price} ask={tick.ask_price} last={tick.last_price}")
            await strategy.on_tick(tick)
            for fill in broker.on_tick(tick):
                print(f"[{label}] fill {fill}")
                print(f"[{label}] account {broker.snapshot()}")
            seen += 1
            if max_ticks is not None and seen >= max_ticks:
                await gateway.close()
                return
    finally:
        if recorder is not None:
            recorder.close()


async def amain() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["binance", "tushare", "efinance", "akshare", "mootdx", "replay"], default="binance")
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--volume", type=float, default=None)
    parser.add_argument("--interval", type=float, default=3.0)
    parser.add_argument("--max-ticks", type=int, default=10)
    parser.add_argument("--record", default=None, help="Optional JSONL file path for recording normalized ticks")
    parser.add_argument("--replay-file", default=None, help="JSONL file recorded by --record")
    parser.add_argument("--replay-speed", type=float, default=0.0, help="Seconds to sleep after each replayed tick")
    parser.add_argument("--tushare-src", default="sina", help="Tushare realtime source, e.g. sina or dc")
    parser.add_argument("--max-errors", type=int, default=10, help="Max consecutive polling errors before failing")
    args = parser.parse_args()

    max_ticks = None if args.max_ticks == 0 else args.max_ticks
    broker = SimBroker(initial_cash=1_000_000.0)

    if args.source == "binance":
        gateway = BinanceSpotGateway(parse_symbols(args.symbols, ["btcusdt"]))
        volume = args.volume if args.volume is not None else 0.001
    elif args.source == "tushare":
        gateway = TushareRealtimeGateway(
            parse_symbols(args.symbols, ["000001.SZ"]),
            interval=args.interval,
            src=args.tushare_src,
            max_consecutive_errors=args.max_errors,
        )
        volume = args.volume if args.volume is not None else 100
    elif args.source == "efinance":
        gateway = EFinanceRealtimeGateway(
            parse_symbols(args.symbols, ["000001.SZ"]),
            interval=args.interval,
            max_consecutive_errors=args.max_errors,
        )
        volume = args.volume if args.volume is not None else 100
    elif args.source == "akshare":
        gateway = AkShareRealtimeGateway(
            parse_symbols(args.symbols, ["000001.SZ"]),
            interval=args.interval,
            max_consecutive_errors=args.max_errors,
        )
        volume = args.volume if args.volume is not None else 100
    elif args.source == "mootdx":
        gateway = MootdxRealtimeGateway(
            parse_symbols(args.symbols, ["000001.SZ"]),
            interval=args.interval,
            max_consecutive_errors=args.max_errors,
        )
        volume = args.volume if args.volume is not None else 100
    else:
        if not args.replay_file:
            raise SystemExit("--replay-file is required when --source replay")
        gateway = ReplayGateway(args.replay_file, speed=args.replay_speed)
        symbols = parse_symbols(args.symbols, [])
        if symbols:
            await gateway.subscribe(symbols)
        volume = args.volume if args.volume is not None else 0.001

    strategy = DemoBuyOnceStrategy(broker=broker, volume=volume)
    await run_loop(args.source, gateway, strategy, broker, max_ticks, record_path=args.record)


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        print("stopped by user")


if __name__ == "__main__":
    main()
