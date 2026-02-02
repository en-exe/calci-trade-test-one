"""Order executor with risk checks."""

from __future__ import annotations

import logging
import uuid
from typing import Any

import config
from src.db import Database
from src.kalshi_client import KalshiClient
from src.strategy import TradeSignal

logger = logging.getLogger(__name__)


async def execute_signals(
    signals: list[TradeSignal],
    client: KalshiClient,
    db: Database,
    balance: int,
) -> int:
    """Execute trade signals, return count of orders placed."""
    placed = 0

    # Daily loss check
    daily_pnl = await db.get_daily_pnl()
    daily_loss_limit = -int(balance * config.MAX_DAILY_LOSS_PCT / 100)
    if daily_pnl <= daily_loss_limit:
        logger.warning("Daily loss limit hit (%d cents). Pausing trading.", daily_pnl)
        return 0

    paused = await db.get_setting("paused", "false")
    if paused == "true":
        logger.info("Trading is paused via settings.")
        return 0

    for signal in signals:
        opp = signal.opportunity
        client_order_id = uuid.uuid4().hex[:16]

        try:
            result = await client.create_order(
                ticker=opp.ticker,
                action="buy",
                side=opp.side,
                count=signal.quantity,
                price=opp.entry_price,
                client_order_id=client_order_id,
            )

            order_id = result.get("order", {}).get("order_id", "")

            await db.insert_trade(
                market_ticker=opp.ticker,
                event_ticker=opp.event_ticker,
                side=opp.side,
                price=opp.entry_price,
                quantity=signal.quantity,
                order_id=order_id,
                client_order_id=client_order_id,
            )

            placed += 1
            logger.info(
                "Order placed: %s %s %s x%d @%dc (order_id=%s)",
                opp.ticker, opp.side, "buy", signal.quantity,
                opp.entry_price, order_id,
            )

        except Exception:
            logger.exception("Failed to place order for %s", opp.ticker)

    return placed
