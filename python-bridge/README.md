# Python SimNow Bridge

This directory contains the Python-based bridge for the simulation framework.

The bridge has two data sources:

- SimNow/CTP through `vnpy` and `vnpy_ctp`.
- Local mock ticks for development while SimNow is unavailable, locked, or under settlement initialization.

## Current status

The bridge is Python-first. It uses `vnpy` and `vnpy_ctp` for SimNow/CTP integration, and FastAPI/WebSocket for downstream simulation clients.

Validated locally so far:

- Python 3.13 virtual environment works.
- `vnpy==4.3.0` and `vnpy_ctp==6.7.11.4` install successfully on Windows with Python 3.13.
- SimNow 7x24 market front `tcp://182.254.243.31:40011` can connect and log in.
- SimNow 7x24 trade front `tcp://182.254.243.31:40001` can connect and authorize.

Known external blocker:

- Trade login may fail if the SimNow account password/status is invalid or temporarily locked. Do not repeatedly retry trade login after error 75.

## Setup

```powershell
E:
cd E:\simnow-ctp
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r python-bridge\requirements.txt
```

For a standalone checkout of this repository, run the same commands from the repository root.

## Config

Copy the example config and fill in the real password locally:

```powershell
copy python-bridge\config.example.json python-bridge\config.json
```

`config.json` must not be committed.

Example:

```json
{
  "investorId": "262600",
  "password": "CHANGE_ME",
  "brokerId": "9999",
  "tdAddress": "tcp://182.254.243.31:40001",
  "mdAddress": "tcp://182.254.243.31:40011",
  "appId": "simnow_client_test",
  "authCode": "0000000000000000"
}
```

## Smoke test: SimNow market data

From `python-bridge`:

```powershell
python run_gateway_md.py au2606.SHFE rb2610.SHFE IF2606.CFFEX
```

Expected gateway logs:

```text
行情服务器连接成功
行情服务器登录成功
订阅行情 -> CTP
```

A successful market data push will print:

```text
[TICK] ...
```

## Bridge server

Start safely without connecting to SimNow:

```powershell
python bridge_server.py
```

Health check:

```text
GET http://127.0.0.1:8765/health
```

WebSocket tick stream:

```text
ws://127.0.0.1:8765/ws/ticks
```

## Local mock tick source

Start the bridge with mock ticks only:

```powershell
python bridge_server.py --mock au2606.SHFE rb2610.SHFE
```

Mock ticks are broadcast to:

```text
ws://127.0.0.1:8765/ws/ticks
```

Start mock ticks after the server is already running:

```powershell
curl -X POST http://127.0.0.1:8765/mock/start `
  -H "Content-Type: application/json" `
  -d "{\"symbols\":[\"au2606.SHFE\",\"rb2610.SHFE\"],\"intervalSeconds\":1}"
```

Stop mock ticks:

```powershell
curl -X POST http://127.0.0.1:8765/mock/stop
```

## SimNow bridge mode

Start and connect to SimNow:

```powershell
python bridge_server.py --connect --subscribe au2606.SHFE
```

The server intentionally does not auto-connect unless `--connect` is passed. This avoids repeated failed trade logins when the SimNow account is locked, inactive, or under settlement initialization.

## Unified strategy/runtime architecture

The local Python bridge now separates strategy, runtime, execution, and matching
concerns so the same strategy class can be used for historical tick replay and
real-time paper trading.

Packages:

- `data/`: canonical `TickData` and `BarData` market-data payloads.
- `strategy/`: `BaseStrategy`, `StrategyContext`, and strategy-emitted
  `OrderIntent` helpers.
- `runtime/`: shared runtime loop plus `SimulationRuntime` for live ticks.
- `execution/`: execution-layer models and `SimulationExecution`, which converts
  `OrderIntent` into `OrderRequest`.
- `simulation/`: realtime paper-trading chain split into `Broker`, `Exchange`,
  and `Matcher`, with `SimulationEngine` kept as the public facade.
- `backtest/`: `BacktestRuntime` and a minimal `BacktestExecution` placeholder
  ready for a future Backtrader wrapper.

Runtime flows:

```text
real tick -> TickData -> BaseStrategy -> OrderIntent -> OrderRequest
          -> SimulationExecution -> SimulationEngine -> Broker -> Exchange
          -> Matcher -> Trade
```

```text
historical tick -> BacktestRuntime -> same BaseStrategy -> BacktestExecution
                -> backtest snapshot/results
```
