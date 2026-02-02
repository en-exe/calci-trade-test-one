"""Market scanner — fetches all open markets and filters for bias opportunities."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import config
from src.kalshi_client import KalshiClient

logger = logging.getLogger(__name__)


class Opportunity:
    """A single trading opportunity detected by the scanner."""

    __slots__ = (
        "ticker", "event_ticker", "title", "yes_price", "no_price",
        "side", "entry_price", "edge", "close_time",
    )

    def __init__(
        self,
        ticker: str,
        event_ticker: str,
        title: str,
        yes_price: int,
        no_price: int,
        side: str,
        entry_price: int,
        edge: float,
        close_time: str,
    ) -> None:
        self.ticker = ticker
        self.event_ticker = event_ticker
        self.title = title
        self.yes_price = yes_price
        self.no_price = no_price
        self.side = side
        self.entry_price = entry_price
        self.edge = edge
        self.close_time = close_time

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


async def scan_markets(client: KalshiClient, timeout_secs: float = 120.0) -> list[Opportunity]:
    """Fetch all open markets and return scored opportunities.

    If scanning takes longer than timeout_secs, returns whatever was found so far.
    """
    opportunities: list[Opportunity] = []
    cursor: str | None = None
    cutoff = datetime.now(timezone.utc) + timedelta(days=config.MAX_EXPIRY_DAYS)
    pages_fetched = 0

    try:
        async with asyncio.timeout(timeout_secs):
            while True:
                data = await client.get_markets(cursor=cursor, limit=1000, status="open")
                markets = data.get("markets", [])
                pages_fetched += 1

                for m in markets:
                    # Filter: must have close_time within expiry window
                    close_time = m.get("close_time", "")
                    if not close_time:
                        continue
                    try:
                        ct = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        continue
                    if ct > cutoff:
                        continue

                    yes_price = m.get("yes_bid", 0) or 0
                    no_price = m.get("no_bid", 0) or 0
                    ticker = m.get("ticker", "")
                    event_ticker = m.get("event_ticker", "")
                    title = m.get("title", "")

                    # Longshot: YES < 10c -> sell YES (buy NO)
                    if 0 < yes_price < config.YES_LOW_THRESHOLD:
                        implied_win = (100 - yes_price) / 100.0
                        if implied_win >= 0.90:
                            entry = 100 - yes_price  # NO price
                            edge = implied_win - 0.5
                            opportunities.append(Opportunity(
                                ticker=ticker, event_ticker=event_ticker, title=title,
                                yes_price=yes_price, no_price=no_price, side="no",
                                entry_price=entry, edge=round(edge, 4),
                                close_time=close_time,
                            ))

                    # Favorite: YES > 85c -> buy YES
                    if yes_price > config.YES_HIGH_THRESHOLD:
                        implied_win = yes_price / 100.0
                        if implied_win >= 0.90:
                            edge = implied_win - 0.5
                            opportunities.append(Opportunity(
                                ticker=ticker, event_ticker=event_ticker, title=title,
                                yes_price=yes_price, no_price=no_price, side="yes",
                                entry_price=yes_price, edge=round(edge, 4),
                                close_time=close_time,
                            ))

                cursor = data.get("cursor")
                if not cursor or not markets:
                    break

    except (asyncio.TimeoutError, TimeoutError):
        logger.warning(
            "Market scan timed out after %.0fs (%d pages fetched, %d opportunities so far)",
            timeout_secs, pages_fetched, len(opportunities),
        )

    # Sort by edge descending
    opportunities.sort(key=lambda o: o.edge, reverse=True)
    logger.info("Scan complete: %d opportunities found (%d pages)", len(opportunities), pages_fetched)
    return opportunities
