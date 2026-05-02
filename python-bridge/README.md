# Python SimNow Bridge

This directory contains the Python-based SimNow/CTP bridge for the simulation framework.

## Current status

The bridge is Python-first. It uses `vnpy` and `vnpy_ctp` to connect to SimNow CTP.

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

## Smoke test

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

Start and connect to SimNow:

```powershell
python bridge_server.py --connect --subscribe au2606.SHFE
```

WebSocket tick stream:

```text
ws://127.0.0.1:8765/ws/ticks
```

The server intentionally does not auto-connect unless `--connect` is passed. This avoids repeated failed trade logins when the SimNow account is locked, inactive, or under settlement initialization.
