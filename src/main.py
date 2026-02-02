"""Entry point — runs the trading loop and FastAPI dashboard in one process."""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

import uvicorn

import config
from src.dashboard import app, init_dashboard
from src.db import Database
from src.executor import execute_signals
from src.kalshi_client import KalshiClient
from src.reconciler import reconcile_trades
from src.scanner import scan_markets
from src.strategy import score_opportunities

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("calci_trade.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("main")

# ---------------------------------------------------------------------------
# Shared state (read by dashboard)
# ---------------------------------------------------------------------------
state: dict = {
    "balance": 0,
    "paused": False,
    "opportunities": [],
}


async def trading_loop(client: KalshiClient, db: Database) -> None:
    """Run one scan-strategy-execute cycle every SCAN_INTERVAL seconds."""
    await db.log_activity("Bot started. Connecting to Kalshi API...", "info")

    while True:
        try:
            # Check pause
            paused = await db.get_setting("paused", "false")
            state["paused"] = paused == "true"
            if state["paused"]:
                await db.log_activity("Trading paused by user.", "warning")
                await asyncio.sleep(config.SCAN_INTERVAL)
                continue

            # Refresh balance
            balance = await client.get_balance()
            state["balance"] = balance
            await db.log_activity(
                f"Balance fetched: ${balance / 100:.2f}", "info"
            )

            # Reconcile open trades
            reconciled = await reconcile_trades(client, db)
            if reconciled:
                await db.log_activity(f"Reconciled {reconciled} open trades.", "info")

            # Scan
            await db.log_activity("Scanning markets for opportunities...", "info")
            opportunities = await scan_markets(client)
            state["opportunities"] = [o.to_dict() for o in opportunities]

            if opportunities:
                top = opportunities[:5]
                summary = ", ".join(
                    f"{o.ticker} ({o.side.upper()} @{o.entry_price}c, edge={o.edge:.1%})"
                    for o in top
                )
                await db.log_activity(
                    f"Found {len(opportunities)} opportunities. Top: {summary}",
                    "success",
                )
            else:
                await db.log_activity(
                    "Scan complete — no opportunities match thresholds.", "info"
                )

            # Get open positions to avoid duplicates
            open_trades = await db.get_open_trades()
            open_tickers = {t["market_ticker"] for t in open_trades}

            # Strategy
            signals = score_opportunities(opportunities, balance, open_tickers)
            if signals:
                await db.log_activity(
                    f"Strategy selected {len(signals)} trades to execute.", "info"
                )

            # Execute
            placed = await execute_signals(signals, client, db, balance)
            if placed:
                await db.log_activity(
                    f"Placed {placed} orders successfully.", "success"
                )

            # Record scan
            await db.insert_scan(
                opportunities_found=len(opportunities),
                trades_placed=placed,
            )

            # Snapshot
            stats = await db.get_trade_stats()
            await db.insert_snapshot(
                balance=balance,
                total_invested=0,
                total_pnl=stats.get("total_pnl", 0) or 0,
                win_count=stats.get("wins", 0) or 0,
                loss_count=stats.get("losses", 0) or 0,
            )

            await db.log_activity(
                f"Cycle complete. Balance=${balance/100:.2f}, "
                f"Opps={len(opportunities)}, Placed={placed}. "
                f"Next scan in {config.SCAN_INTERVAL}s.",
                "info",
            )

        except Exception as exc:
            logger.exception("Error in trading loop")
            try:
                await db.log_activity(f"ERROR: {exc}", "error")
            except Exception:
                pass

        await asyncio.sleep(config.SCAN_INTERVAL)


@asynccontextmanager
async def lifespan(application):
    db = Database()
    await db.connect()
    client = KalshiClient()

    init_dashboard(db, state)

    task = asyncio.create_task(trading_loop(client, db))
    logger.info("Trading loop started. Dashboard at http://localhost:8080")

    yield

    task.cancel()
    await client.close()
    await db.close()


app.router.lifespan_context = lifespan


def main() -> None:
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8080,
        log_level="info",
    )


if __name__ == "__main__":
    main()
