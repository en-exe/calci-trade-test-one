# Kalshi Trading Bot — Favorite-Longshot Bias Exploiter

## Strategy

Academic research on 72.1M trades confirms: contracts priced <10c lose >60% of invested money. We systematically **sell against longshots** (buy NO on cheap YES contracts) and **buy near-certain outcomes** (buy YES on contracts >85c) across ALL categories on Kalshi. The bias is universal across all market categories.

**Flow**:
1. Scan all active markets every 5 minutes
2. Find contracts where YES is priced <10c → buy NO at 90c+
3. Find contracts where YES is priced >85c → buy YES
4. Hold to settlement, collect winnings, compound all profits

## Tech Stack

- Python 3, httpx (async HTTP), cryptography (RSA-PSS), SQLite, FastAPI + Jinja2 + Chart.js CDN, uvicorn
- Single process: trading loop + web dashboard
- Target: $5 VPS, ~50-80MB RAM

## Project Structure

```
src/
├── kalshi_client.py      # Auth + API calls
├── scanner.py            # Market scanning + filtering
├── strategy.py           # Scoring + decision logic
├── executor.py           # Order placement + risk checks
├── db.py                 # SQLite schema + queries
├── dashboard.py          # FastAPI routes + templates
├── main.py               # Entry point
└── templates/
    ├── base.html
    ├── dashboard.html
    ├── trades.html
    └── markets.html
config.py
requirements.txt
.env
.gitignore
```

## Kalshi API Reference

- **Auth**: RSA-PSS signatures. Sign `{timestamp_ms}{METHOD}{path}` with SHA-256, MGF1-SHA256. Headers: `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP`, `KALSHI-ACCESS-SIGNATURE` (base64).
- **Production**: `https://api.elections.kalshi.com/trade-api/v2`
- **Demo**: `https://demo-api.kalshi.co/trade-api/v2`
- **GET /markets** — list markets (up to 1000/page, cursor pagination)
- **GET /markets/{ticker}** — single market detail
- **GET /markets/{ticker}/orderbook** — bids only (YES bids + NO bids; ask = 100 - opposite bid)
- **GET /portfolio/balance** — balance in cents
- **GET /portfolio/positions** — open positions
- **POST /portfolio/orders** — create order: `{ticker, action, side, count, type:"limit", yes_price/no_price, client_order_id}`
- **DELETE /portfolio/orders/{order_id}** — cancel order
- **GET /portfolio/fills** — trade history
- **GET /portfolio/settlements** — settlement P&L
- Rate limits: Basic tier = 20 reads/sec, 10 writes/sec

## Database Schema (SQLite)

```sql
CREATE TABLE trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_ticker TEXT NOT NULL,
    event_ticker TEXT,
    side TEXT NOT NULL,        -- 'yes' or 'no'
    action TEXT NOT NULL,      -- 'buy' or 'sell'
    price INTEGER NOT NULL,    -- in cents (1-99)
    quantity INTEGER NOT NULL,
    order_id TEXT,
    client_order_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'open', -- open, filled, settled_win, settled_loss, cancelled
    pnl INTEGER DEFAULT 0      -- in cents
);

CREATE TABLE portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    balance INTEGER NOT NULL,   -- cents
    total_invested INTEGER,
    total_pnl INTEGER,
    win_count INTEGER DEFAULT 0,
    loss_count INTEGER DEFAULT 0
);

CREATE TABLE market_scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    markets_scanned INTEGER,
    opportunities_found INTEGER,
    trades_placed INTEGER
);

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
```

## Risk Management Rules

- Max 20% of portfolio on any single market
- Keep 20% cash reserve (only use 80% of balance)
- Only trade contracts expiring within 7 days
- Min edge: implied win rate >90%
- Daily loss limit: pause trading if portfolio drops >15% in a day

## Dashboard Pages

- **`/`** (Dashboard): balance, total P&L, win rate %, equity curve (Chart.js line chart), active positions count, today's trades summary
- **`/trades`** (Trade Log): table of all trades — ticker, side, price, quantity, status, P&L, timestamp. Sortable.
- **`/markets`** (Scanner): current opportunities detected, edge scores, position status
- **`/api/snapshot`** (JSON): latest portfolio snapshot for Chart.js to poll

---

# BUILD TASKS (for subagents)

## Task 1: Core API Client (`src/kalshi_client.py` + `config.py` + `requirements.txt` + `.gitignore`)

Build the Kalshi API client with RSA-PSS authentication.

**Files to create**: `src/kalshi_client.py`, `config.py`, `requirements.txt`, `.gitignore`

**Requirements**:
- `config.py`: reads `.env` for `KALSHI_API_KEY`, `KALSHI_PRIVATE_KEY_PATH`, `KALSHI_BASE_URL` (default to demo). Also define constants: `SCAN_INTERVAL=300`, `YES_LOW_THRESHOLD=10`, `YES_HIGH_THRESHOLD=85`, `MAX_POSITION_PCT=20`, `CASH_RESERVE_PCT=20`, `MAX_DAILY_LOSS_PCT=15`, `MAX_EXPIRY_DAYS=7`.
- `KalshiClient` class with async methods:
  - `_sign_request(method, path)` → returns headers dict with timestamp + signature
  - `get_balance()` → returns balance in cents
  - `get_markets(cursor=None, limit=1000, status="open")` → returns list of markets
  - `get_market(ticker)` → returns single market
  - `get_orderbook(ticker)` → returns orderbook
  - `get_positions()` → returns open positions
  - `create_order(ticker, action, side, count, price, client_order_id)` → returns order
  - `cancel_order(order_id)` → cancels order
  - `get_fills()` → returns fill history
  - `get_settlements()` → returns settlement records
- `requirements.txt`: httpx, cryptography, python-dotenv, fastapi, uvicorn, jinja2
- `.gitignore`: .env, __pycache__, *.db, *.pyc, .venv/

**Auth implementation**: Read PEM private key file. For each request, build string `{timestamp_ms}{METHOD}{path}` (path without query params). Sign with RSA-PSS (SHA-256 hash, MGF1-SHA256, salt_length=digest_size). Base64 encode signature. Set 3 headers.

## Task 2: Database Layer (`src/db.py`)

**Files to create**: `src/db.py`

**Requirements**:
- `init_db()` — creates all tables from schema above if not exist
- `record_trade(market_ticker, event_ticker, side, action, price, quantity, order_id, client_order_id)` → inserts trade
- `update_trade_status(order_id, status, pnl)` → updates trade outcome
- `get_open_trades()` → returns all trades with status='open' or 'filled'
- `get_all_trades(limit=100, offset=0)` → returns trades for dashboard
- `get_today_trades()` → trades from today
- `record_snapshot(balance, total_invested, total_pnl, win_count, loss_count)` → inserts snapshot
- `get_snapshots(limit=100)` → for equity curve
- `get_latest_snapshot()` → current state
- `record_scan(markets_scanned, opportunities_found, trades_placed)` → inserts scan record
- `get_setting(key)` / `set_setting(key, value)` → runtime config
- `get_daily_pnl()` → sum of today's P&L for loss limit check
- `get_stats()` → dict with total trades, win rate, total P&L, etc.
- Use `aiosqlite` for async compatibility. DB file at `./trading_bot.db`.

## Task 3: Scanner + Strategy (`src/scanner.py` + `src/strategy.py`)

**Files to create**: `src/scanner.py`, `src/strategy.py`

**Scanner** (`scanner.py`):
- `scan_markets(client: KalshiClient)` → fetches all open markets (paginate with cursor), returns list of opportunity dicts
- For each market, check: `yes_price` (from orderbook best ask = 100 - best NO bid), days until expiry
- Filter to markets where: (yes_price <= YES_LOW_THRESHOLD OR yes_price >= YES_HIGH_THRESHOLD) AND expiry within MAX_EXPIRY_DAYS
- Return list of `{ticker, event_ticker, yes_price, no_price, expiry, volume, edge_score}`

**Strategy** (`strategy.py`):
- `score_opportunity(market_data)` → returns edge score (0-100)
  - For low YES price (<10c): edge = historical_loss_rate (60%+) minus implied probability. Higher = better.
  - For high YES price (>85c): edge = implied win rate minus 85%. Higher = better.
  - Bonus points for: higher volume (more liquid), closer to expiry (more certain), lower price for longshots
- `select_trades(opportunities, balance, open_positions)` → returns list of trades to execute
  - Sort by edge score descending
  - Allocate capital: max 20% per market, max 80% total
  - Skip markets we already have positions in
  - Return: `[{ticker, side, action, price, quantity}]`

## Task 4: Executor (`src/executor.py`)

**Files to create**: `src/executor.py`

**Requirements**:
- `execute_trades(client, db, trades)` → places orders and records them
  - For each trade: generate UUID client_order_id, call `client.create_order()`, call `db.record_trade()`
  - Handle errors gracefully (log + skip, don't crash)
- `check_settlements(client, db)` → checks settlement status of open trades
  - Get fills and settlements from API
  - Update trade status in DB (settled_win / settled_loss)
  - Calculate and record P&L
- `check_risk_limits(db, balance)` → returns True if safe to trade
  - Check daily P&L against MAX_DAILY_LOSS_PCT
  - Check if trading is paused via settings table
- `take_snapshot(client, db)` → records current portfolio state to DB

## Task 5: Dashboard (`src/dashboard.py` + `src/templates/*.html`)

**Files to create**: `src/dashboard.py`, `src/templates/base.html`, `src/templates/dashboard.html`, `src/templates/trades.html`, `src/templates/markets.html`

**Dashboard** (`dashboard.py`):
- FastAPI app with Jinja2 templates
- `GET /` → renders dashboard.html with latest snapshot, today's trades, active positions
- `GET /trades` → renders trades.html with paginated trade log
- `GET /markets` → renders markets.html with latest scan results (store in memory or DB)
- `GET /api/snapshots` → JSON array of snapshots for Chart.js equity curve
- `GET /api/stats` → JSON stats dict
- `POST /api/pause` → set pause setting
- `POST /api/resume` → clear pause setting

**Templates**:
- `base.html`: simple HTML5 layout, nav bar (Dashboard | Trades | Markets), dark theme, minimal CSS (inline or <style> tag), Chart.js from CDN
- `dashboard.html`: balance card, P&L card, win rate card, equity curve chart, recent trades table (last 10)
- `trades.html`: full trade log table with columns: time, ticker, side, price, qty, status, P&L
- `markets.html`: current opportunities table: ticker, yes_price, edge_score, in_position, expiry

Keep the CSS minimal and dark-themed. No external CSS frameworks — just clean inline styles or a single <style> block in base.html.

## Task 6: Main Entry Point (`src/main.py`)

**Files to create**: `src/main.py`

**Requirements**:
- Initialize DB, KalshiClient, FastAPI dashboard
- Run two concurrent tasks via asyncio:
  1. **Trading loop**: every SCAN_INTERVAL seconds: scan markets → score → check risk → execute trades → check settlements → take snapshot → log results
  2. **Web server**: uvicorn serving the dashboard on 0.0.0.0:8080
- Use `asyncio.gather()` to run both
- Graceful shutdown on SIGINT/SIGTERM
- Log all actions to `trading_bot.log`
- On startup: log balance, run initial scan, report opportunity count
