# Binance Futures Testnet Trading Bot

A production-grade Python trading bot for the Binance Futures Testnet (USDT-M). Supports Market, Limit, Stop-Market, Stop-Limit, and TWAP order types via a typed CLI with Rich terminal output and structured logging.

---

## Project structure

```
trading_bot/
├── bot/
│   ├── __init__.py          # public exports
│   ├── client.py            # Binance REST client — signing, auth, HTTP
│   ├── orders.py            # order placement logic
│   ├── validators.py        # live constraint validation via exchange info API
│   ├── twap.py              # TWAP execution algorithm
│   └── logging_config.py    # structured file + console logging
├── logs/                    # auto-created on first run
│   └── trading_bot.log
├── cli.py                   # CLI entry point (Typer)
├── .env                     # API credentials — never commit
├── .env.example             # template for .env
├── .gitignore
└── requirements.txt
```

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/your-username/trading-bot.git
cd trading-bot
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure credentials

Open `.env` and fill in your keys:

```
BINANCE_API_KEY=your_testnet_api_key_here
BINANCE_SECRET_KEY=your_testnet_secret_key_here
```


### 5. Verify setup

```bash
python -c "from bot.client import BinanceClient; c = BinanceClient(); print('Client OK')"
```

---

## Running the bot

All commands are run from the `trading_bot/` directory with the virtual environment active.

---

### Interactive mode (recommended for manual use)

Guided menu-driven order placement with prompts and live validation at each step.

```bash
python cli.py interactive
```

---

### Place command (one-shot via flags)

Place a single order directly from CLI arguments. All fields can be passed as flags or entered via prompt if omitted.

```bash
python cli.py place [OPTIONS]
```

#### Market orders

```bash
# Market BUY — execute immediately at current price
python cli.py place --symbol BTCUSDT --side BUY --type MARKET --quantity 0.001 --yes

# Market SELL
python cli.py place --symbol BTCUSDT --side SELL --type MARKET --quantity 0.001 --yes

# Short form flags
python cli.py place -s BTCUSDT --side BUY -t MARKET -q 0.001 -y
```

#### Limit orders

```bash
# Limit BUY — buy only if price drops to 60000
python cli.py place -s BTCUSDT --side BUY -t LIMIT -q 0.001 -p 60000.0 -y

# Limit SELL — sell only if price rises to 75000
python cli.py place -s BTCUSDT --side SELL -t LIMIT -q 0.001 -p 75000.0 -y

# With custom time-in-force (default is GTC)
python cli.py place -s BTCUSDT --side BUY -t LIMIT -q 0.001 -p 60000.0 --tif IOC -y
```

#### Stop-Market orders

Triggers a market order when price hits the stop level.

```bash
# SELL stop-market — stop-loss: trigger market sell if price drops to 59000
python cli.py place -s BTCUSDT --side SELL -t STOP_MARKET -q 0.001 --stop-price 59000.0 -y

# BUY stop-market — breakout entry: trigger market buy if price rises to 70000
python cli.py place -s BTCUSDT --side BUY -t STOP_MARKET -q 0.001 --stop-price 70000.0 -y
```

---

### Stop-Limit orders

Two prices required: a trigger (`--stop-price`) and an execution floor/ceiling (`--price`).

```bash
# SELL stop-limit — trigger at 59000, execute no lower than 58500
python cli.py stop-limit \
  --symbol BTCUSDT \
  --side SELL \
  --quantity 0.001 \
  --stop-price 59000.0 \
  --price 58500.0 \
  --yes

# BUY stop-limit — trigger at 70000, execute no higher than 70500
python cli.py stop-limit -s BTCUSDT --side BUY -q 0.001 --stop-price 70000.0 -p 70500.0 -y
```

---

### TWAP orders

Splits a large order into equal slices executed at regular intervals to reduce market impact.

```bash
# Buy 0.05 BTC in 5 slices, one every 60 seconds (~5 minutes total)
python cli.py twap --symbol BTCUSDT --side BUY --quantity 0.05 --slices 5 --interval 60

# Sell 0.03 BTC in 3 slices, one every 30 seconds
python cli.py twap -s BTCUSDT --side SELL -q 0.03 --slices 3 --interval 30 --yes

# Fast test: 3 slices, 5 seconds apart
python cli.py twap -s BTCUSDT --side BUY -q 0.003 --slices 3 --interval 5 --yes
```


---

### Built-in help

```bash
# List all commands
python cli.py --help

# Help for a specific command
python cli.py place --help
python cli.py twap --help
python cli.py stop-limit --help
```

---

## Order types reference

| Type | Flag value | Description |
|---|---|---|
| Market | `MARKET` | Execute immediately at best available price |
| Limit | `LIMIT` | Execute only at specified price or better |
| Stop-Market | `STOP_MARKET` | Market order triggered when price hits stop level |
| Stop-Limit | `stop-limit` command | Limit order triggered when price hits stop level |
| TWAP | `twap` command | Splits order into time-distributed slices |

---

## Validation

All inputs are validated against live Binance exchange rules before any order is sent:

- **Symbol** — normalised and checked against `/fapi/v1/exchangeInfo`
- **Quantity** — validated against `LOT_SIZE` filter (min, max, step size)
- **Price** — validated against `PRICE_FILTER` (min, max, tick size)
- **Notional** — order value checked against `MIN_NOTIONAL` filter
- **Stop prices** — directional logic checked (BUY stop must be above market, SELL below)

Validation errors are printed clearly before any network call is made.

---

## Logging

All API requests, responses, and errors are written to `logs/trading_bot.log`.

```
2026-03-29 12:34:56 | INFO     | client    | POST /fapi/v1/order | params={...}
2026-03-29 12:34:56 | INFO     | orders    | Order placed | id=2938471623 | status=FILLED
2026-03-29 12:34:57 | DEBUG    | client    | Response | status=200 | body={...}
2026-03-29 12:34:58 | ERROR    | client    | API rejected order: code=-1121 msg=Invalid symbol
```

Log levels:
- `DEBUG` — full request/response bodies (file only)
- `INFO` — order placement events, status changes (file + console)
- `WARNING` — soft failures, cache misses (file + console)
- `ERROR` — API rejections, network failures (file + console)

---

## Assumptions

- All orders are placed on the **Binance Futures Testnet** (USDT-M). No real funds are used.
- Timestamp drift between local machine and Binance servers is corrected automatically via `/fapi/v1/time` on client startup.
- Exchange constraints (step size, tick size, min notional) are fetched live from `/fapi/v1/exchangeInfo` and cached per process. Restart to refresh.
- TWAP uses **market orders** for each slice to guarantee fills. Partial execution (some slices fail) is tolerated — the executor continues remaining slices.
- OCO orders are not supported — they are a Spot-only feature not available on Binance Futures.
- Default `timeInForce` for Limit and Stop-Limit orders is `GTC` (Good Till Cancelled).

---

## Requirements

See `requirements.txt` for pinned versions. Core dependencies:

```
requests
python-dotenv
typer
rich
```

---

## Common errors

| Error | Cause | Fix |
|---|---|---|
| `BinanceAuthError` | Missing or empty API keys | Check `.env` file |
| `-1021 Timestamp outside recvWindow` | System clock drift | Restart the bot — client auto-syncs on init |
| `-1121 Invalid symbol` | Symbol not on Futures testnet | Use `BTCUSDT`, `ETHUSDT`, etc. |
| `-2010 Insufficient balance` | Not enough testnet USDT | Request testnet funds from the testnet UI |
| `-1111 Precision is over the maximum` | Quantity or price precision too high | Check step size and tick size for the symbol |