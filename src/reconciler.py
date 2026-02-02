"""Reconciler — checks fills and settlements to update trade outcomes."""

from __future__ import annotations
import logging
from src.db import Database
from src.kalshi_client import KalshiClient

logger = logging.getLogger(__name__)


async def reconcile_trades(client: KalshiClient, db: Database) -> int:
    """Check open trades against Kalshi API and update their status/P&L.

    Returns count of trades updated.
    """
    open_trades = await db.get_open_trades()
    if not open_trades:
        return 0

    updated = 0

    # 1. Check portfolio positions from Kalshi to see what's still active
    try:
        positions_data = await client.get_positions()
        # positions_data has market_positions list with ticker, position, etc.
        active_tickers = set()
        for pos in positions_data.get("market_positions", []):
            ticker = pos.get("ticker", "")
            # A position with non-zero quantity is still active
            yes_count = pos.get("position", 0)
            no_count = pos.get("total_traded", 0)
            if yes_count != 0 or no_count != 0:
                active_tickers.add(ticker)
    except Exception:
        logger.exception("Failed to fetch positions for reconciliation")
        return 0

    # 2. Check settlements
    try:
        settlements_data = await client.get_settlements()
        settled_tickers = {}
        for s in settlements_data.get("settlements", []):
            ticker = s.get("market_ticker", "")
            revenue = s.get("revenue", 0)  # cents gained/lost
            settled_tickers[ticker] = revenue
    except Exception:
        logger.exception("Failed to fetch settlements")
        settled_tickers = {}

    # 3. Check fills to verify orders actually executed
    try:
        fills_data = await client.get_fills()
        filled_order_ids = set()
        for f in fills_data.get("fills", []):
            filled_order_ids.add(f.get("order_id", ""))
    except Exception:
        logger.exception("Failed to fetch fills")
        filled_order_ids = set()

    # 4. Update each open trade
    for trade in open_trades:
        trade_id = trade["id"]
        ticker = trade["market_ticker"]
        order_id = trade["order_id"]
        side = trade["side"]
        price = trade["price"]
        quantity = trade["quantity"]
        cost = price * quantity

        # Check if settled
        if ticker in settled_tickers:
            revenue = settled_tickers[ticker]
            pnl = revenue - cost if revenue > 0 else -cost
            # If we bought NO and NO wins, we get 100c per contract
            # If we bought YES and YES wins, we get 100c per contract
            status = "settled" if revenue > 0 else "lost"
            await db.update_trade_status(trade_id, status, pnl)
            logger.info("Trade %d (%s) %s: revenue=%d, pnl=%d", trade_id, ticker, status, revenue, pnl)
            updated += 1
            continue

        # Check if the order was never filled (not in fills and not in active positions)
        if order_id and order_id not in filled_order_ids and ticker not in active_tickers:
            # Order likely expired unfilled
            await db.update_trade_status(trade_id, "expired", 0)
            logger.info("Trade %d (%s) marked as expired (unfilled)", trade_id, ticker)
            updated += 1
            continue

    if updated:
        await db.log_activity(f"Reconciled {updated} trades.", "info")

    return updated
