"""Strategy module — scores opportunities and decides position sizing."""

from __future__ import annotations

import logging
from typing import Any

import config
from src.scanner import Opportunity

logger = logging.getLogger(__name__)


class TradeSignal:
    """A sized trade recommendation ready for execution."""

    __slots__ = ("opportunity", "quantity", "reason")

    def __init__(self, opportunity: Opportunity, quantity: int, reason: str) -> None:
        self.opportunity = opportunity
        self.quantity = quantity
        self.reason = reason

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.opportunity.to_dict(),
            "quantity": self.quantity,
            "reason": self.reason,
        }


def score_opportunities(
    opportunities: list[Opportunity],
    balance: int,
    open_tickers: set[str],
) -> list[TradeSignal]:
    """Filter and size opportunities given current portfolio state.

    Args:
        opportunities: Sorted list from scanner.
        balance: Current portfolio balance in cents.
        open_tickers: Set of market tickers we already have open positions in.

    Returns:
        List of TradeSignal objects ready for execution.
    """
    signals: list[TradeSignal] = []
    available = int(balance * (1 - config.CASH_RESERVE_PCT / 100))
    max_per_market = int(balance * config.MAX_POSITION_PCT / 100)

    for opp in opportunities:
        if opp.ticker in open_tickers:
            continue

        if available <= 0:
            break

        # Position size: min of max_per_market and remaining available
        budget = min(max_per_market, available)
        quantity = budget // opp.entry_price
        if quantity < 1:
            continue

        cost = quantity * opp.entry_price
        available -= cost

        reason = (
            f"{'Longshot fade' if opp.side == 'no' else 'Favorite back'}: "
            f"YES@{opp.yes_price}c, edge={opp.edge:.1%}"
        )

        signals.append(TradeSignal(opportunity=opp, quantity=quantity, reason=reason))

    logger.info("Strategy produced %d signals from %d opportunities",
                len(signals), len(opportunities))
    return signals
