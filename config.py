"""Configuration loaded from environment variables and sensible defaults."""

import os
from dotenv import load_dotenv

load_dotenv()

# --- Kalshi API credentials ---
KALSHI_API_KEY: str = os.getenv("KALSHI_API_KEY", "")
KALSHI_PRIVATE_KEY_PATH: str = os.getenv("KALSHI_PRIVATE_KEY_PATH", "./bot.txt")
KALSHI_BASE_URL: str = os.getenv(
    "KALSHI_BASE_URL", "https://demo-api.kalshi.co/trade-api/v2"
)

# --- Trading parameters ---
SCAN_INTERVAL: int = 300  # seconds between market scans
YES_LOW_THRESHOLD: int = 10  # cents – longshot ceiling
YES_HIGH_THRESHOLD: int = 85  # cents – favourite floor
MAX_POSITION_PCT: int = 20  # max % of portfolio on one market
CASH_RESERVE_PCT: int = 20  # keep 20 % cash at all times
MAX_DAILY_LOSS_PCT: int = 15  # pause if daily loss exceeds this %
MAX_EXPIRY_DAYS: int = 7  # only trade contracts expiring within N days
