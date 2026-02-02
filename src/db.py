"""SQLite database layer using aiosqlite."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = "calci_trade.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_ticker TEXT NOT NULL,
    event_ticker TEXT NOT NULL DEFAULT '',
    side TEXT NOT NULL,          -- 'yes' or 'no'
    price INTEGER NOT NULL,      -- cents
    quantity INTEGER NOT NULL,
    order_id TEXT NOT NULL DEFAULT '',
    client_order_id TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',  -- open / settled / lost
    pnl INTEGER DEFAULT 0        -- cents
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    balance INTEGER NOT NULL,
    total_invested INTEGER NOT NULL DEFAULT 0,
    total_pnl INTEGER NOT NULL DEFAULT 0,
    win_count INTEGER NOT NULL DEFAULT 0,
    loss_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS market_scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    opportunities_found INTEGER NOT NULL DEFAULT 0,
    trades_placed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',  -- info / success / warning / error
    message TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str = DB_PATH) -> None:
        self._path = path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        logger.info("Database connected: %s", self._path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "Database not connected"
        return self._db

    # ---- trades ----

    async def insert_trade(
        self,
        market_ticker: str,
        event_ticker: str,
        side: str,
        price: int,
        quantity: int,
        order_id: str,
        client_order_id: str,
    ) -> int:
        cur = await self.db.execute(
            """INSERT INTO trades
               (market_ticker, event_ticker, side, price, quantity,
                order_id, client_order_id, timestamp, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open')""",
            (
                market_ticker,
                event_ticker,
                side,
                price,
                quantity,
                order_id,
                client_order_id,
                datetime.utcnow().isoformat(),
            ),
        )
        await self.db.commit()
        return cur.lastrowid  # type: ignore[return-value]

    async def update_trade_status(
        self, trade_id: int, status: str, pnl: int = 0
    ) -> None:
        await self.db.execute(
            "UPDATE trades SET status = ?, pnl = ? WHERE id = ?",
            (status, pnl, trade_id),
        )
        await self.db.commit()

    async def get_open_trades(self) -> list[dict[str, Any]]:
        cur = await self.db.execute(
            "SELECT * FROM trades WHERE status = 'open' ORDER BY timestamp DESC"
        )
        return [dict(r) for r in await cur.fetchall()]

    async def get_all_trades(self, limit: int = 200) -> list[dict[str, Any]]:
        cur = await self.db.execute(
            "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in await cur.fetchall()]

    async def get_today_trades(self) -> list[dict[str, Any]]:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        cur = await self.db.execute(
            "SELECT * FROM trades WHERE timestamp LIKE ? ORDER BY timestamp DESC",
            (f"{today}%",),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def get_trade_stats(self) -> dict[str, Any]:
        cur = await self.db.execute(
            """SELECT
                 COUNT(*) as total,
                 SUM(CASE WHEN status='settled' THEN 1 ELSE 0 END) as wins,
                 SUM(CASE WHEN status='lost' THEN 1 ELSE 0 END) as losses,
                 SUM(pnl) as total_pnl
               FROM trades"""
        )
        row = await cur.fetchone()
        return dict(row) if row else {"total": 0, "wins": 0, "losses": 0, "total_pnl": 0}

    # ---- portfolio snapshots ----

    async def insert_snapshot(
        self, balance: int, total_invested: int, total_pnl: int,
        win_count: int, loss_count: int,
    ) -> None:
        await self.db.execute(
            """INSERT INTO portfolio_snapshots
               (timestamp, balance, total_invested, total_pnl, win_count, loss_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (datetime.utcnow().isoformat(), balance, total_invested, total_pnl,
             win_count, loss_count),
        )
        await self.db.commit()

    async def get_snapshots(self, limit: int = 100) -> list[dict[str, Any]]:
        cur = await self.db.execute(
            "SELECT * FROM portfolio_snapshots ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in await cur.fetchall()]

    # ---- market scans ----

    async def insert_scan(self, opportunities_found: int, trades_placed: int) -> None:
        await self.db.execute(
            "INSERT INTO market_scans (timestamp, opportunities_found, trades_placed) VALUES (?, ?, ?)",
            (datetime.utcnow().isoformat(), opportunities_found, trades_placed),
        )
        await self.db.commit()

    async def get_recent_scans(self, limit: int = 20) -> list[dict[str, Any]]:
        cur = await self.db.execute(
            "SELECT * FROM market_scans ORDER BY timestamp DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in await cur.fetchall()]

    # ---- settings ----

    async def get_setting(self, key: str, default: str = "") -> str:
        cur = await self.db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cur.fetchone()
        return row["value"] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        await self.db.commit()

    # ---- activity log ----

    async def log_activity(self, message: str, level: str = "info") -> None:
        await self.db.execute(
            "INSERT INTO activity_log (timestamp, level, message) VALUES (?, ?, ?)",
            (datetime.utcnow().isoformat(), level, message),
        )
        await self.db.commit()

    async def get_activity_log(self, limit: int = 50) -> list[dict[str, Any]]:
        cur = await self.db.execute(
            "SELECT * FROM activity_log ORDER BY timestamp DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in await cur.fetchall()]

    # ---- daily P&L ----

    async def get_daily_pnl(self) -> int:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        cur = await self.db.execute(
            "SELECT COALESCE(SUM(pnl), 0) as dpnl FROM trades WHERE timestamp LIKE ?",
            (f"{today}%",),
        )
        row = await cur.fetchone()
        return row["dpnl"] if row else 0
