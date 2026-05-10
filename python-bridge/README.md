# Python SimNow Bridge

This directory contains the Python-based bridge for the simulation framework.

The bridge has these data sources:

- SimNow/CTP through `vnpy` and `vnpy_ctp`.
- Local mock ticks for development while SimNow is unavailable, locked, or under settlement initialization.
- Binance public WebSocket market data through `binance_bridge_server.py`.

## Current status

The bridge is Python-first. It uses `vnpy` and `vnpy_ctp` for SimNow/CTP integration, and FastAPI/WebSocket for downstream simulation clients.

Validated locally so far:

- Python 3.13 virtual environment works.
- `vnpy==4.3.0` and `vnpy_ctp==6.7.11.4` install successfully on Windows with Python 3.13.
- SimNow 7x24 market front `tcp://182.254.243.31:40011` can connect and log in.
- SimNow 7x24 trade front `tcp://182.254.243.31:40001` can connect and authorize.
- Local paper-trading simulation engine supports order matching, account state, position state, and callbacks.
- Binance bridge can consume public bookTicker WebSocket data and feed ticks into the local simulation engine.

Known external blockers:

- Trade login may fail if the SimNow account password/status is invalid or temporarily locked. Do not repeatedly retry trade login after error 75.
- Binance REST/WebSocket access may return HTTP 451 in restricted regions or networks. This is an upstream access restriction, not a local strategy or CSV parsing error.

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

## Binance real-time tick bridge

This mode consumes Binance public bookTicker WebSocket streams and feeds converted ticks into `SimulationEngine`. No Binance API key is required because it only uses public market data.

Install dependencies from `python-bridge`:

```bash
pip install -r requirements.txt
```

Start real-time Binance ticks:

```bash
python binance_bridge_server.py --binance BTCUSDT ETHUSDT BNBUSDT
```

Health check in another terminal:

```bash
curl http://127.0.0.1:8765/health
```

Expected health fields:

```text
binanceRunning: true
binanceSymbols: ["BNBUSDT", "BTCUSDT", "ETHUSDT"]
lastTick: not null
marketDataFresh: true
```

Submit a simulated market buy order:

```bash
curl -X POST http://127.0.0.1:8765/simulation/orders \
  -H "Content-Type: application/json" \
  -d '{"vtSymbol":"BTCUSDT.BINANCE","direction":"LONG","offset":"OPEN","price":1,"volume":1,"orderType":"MARKET"}'
```

Query simulation state:

```bash
curl http://127.0.0.1:8765/simulation/account
curl http://127.0.0.1:8765/simulation/positions
curl http://127.0.0.1:8765/simulation/trades
```

Important distinction:

- `binance_bridge_server.py` is for real-time paper trading / forward simulation from live ticks.
- `scripts/download_binance_klines.py` is for historical K-line download and backtesting.
- If REST K-line download returns HTTP 451, use real-time WebSocket mode or a legally permitted data source for your region.
