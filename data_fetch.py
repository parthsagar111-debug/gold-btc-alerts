"""
Fetches 1H candle data for Gold (XAU/USD) and Bitcoin (BTC/USD).

Gold    -> Twelve Data API (free tier, needs TWELVE_DATA_API_KEY env var)
Bitcoin -> CoinGecko API (free Demo plan, needs COINGECKO_API_KEY env var
           for a stable 100 calls/min - the old no-key public pool only
           gives 5-15 calls/min shared globally, which we kept hitting)
"""

import os
import requests
import pandas as pd
from datetime import datetime, timezone


TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "")
COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "")


def fetch_gold_1h(outputsize: int = 150) -> pd.DataFrame:
    """
    Fetches recent 1H XAU/USD candles from Twelve Data, including full OHLC
    (not just Close) - needed for Level 3 candlestick pattern detection,
    which depends on candle shape (open/high/low/close relationships), not
    just the closing price.
    outputsize=150 gives enough history for EMA50 + MACD warmup.
    """
    if not TWELVE_DATA_API_KEY:
        raise RuntimeError(
            "TWELVE_DATA_API_KEY environment variable not set. "
            "Set it in Render's Environment tab, never hardcode it."
        )

    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": "XAU/USD",
        "interval": "1h",
        "outputsize": outputsize,
        "apikey": TWELVE_DATA_API_KEY,
    }
    resp = requests.get(url, params=params, timeout=15)
    data = resp.json()

    if "values" not in data:
        raise RuntimeError(f"Twelve Data error: {data}")

    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime").sort_index()
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)
    df = df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"})
    return df[["Open", "High", "Low", "Close"]]


def fetch_bitcoin_1h(days: int = 30) -> pd.DataFrame:
    """
    Fetches recent BTC/USD OHLC candles from CoinGecko's dedicated /ohlc
    endpoint (not /market_chart, which only returns Close-equivalent price
    points with no Open/High/Low - insufficient for Level 3 candlestick
    pattern detection).

    IMPORTANT: the /ohlc endpoint's `days` parameter only accepts specific
    values: 1, 7, 14, 30, 90, 180, 365, or "max" - NOT arbitrary integers.
    Passing days=4 (as an earlier version of this code did) returns an
    "Invalid days parameter" error. Granularity is automatic based on the
    days value: 1-2 days -> 30 min candles, 3-30 days -> 4 hour candles,
    31+ days -> 4 day candles. We use days=30 (the largest value that still
    gives 4-hour granularity) to get ~180 candles, comfortably covering our
    150-candle requirement for EMA50 + MACD warmup.

    Uses the free Demo plan API key (100 calls/min) via the
    x-cg-demo-api-key header. Falls back to the old no-key public endpoint
    if COINGECKO_API_KEY isn't set, though that's heavily rate-limited
    (5-15 calls/min, shared globally) and not recommended.
    """
    url = "https://api.coingecko.com/api/v3/coins/bitcoin/ohlc"
    params = {"vs_currency": "usd", "days": days}
    headers = {}
    if COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = COINGECKO_API_KEY

    resp = requests.get(url, params=params, headers=headers, timeout=15)

    if resp.status_code == 429:
        raise RuntimeError(
            "CoinGecko rate limit hit (429). This is usually temporary - "
            "it resets within a few minutes. If it persists and you have "
            "COINGECKO_API_KEY set, check the key is correct on the "
            "Developer Dashboard."
        )

    data = resp.json()

    if not isinstance(data, list):
        raise RuntimeError(f"CoinGecko error: {data}")

    # Each row: [timestamp_ms, open, high, low, close]
    df = pd.DataFrame(data, columns=["timestamp", "Open", "High", "Low", "Close"])
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("datetime").sort_index()
    return df[["Open", "High", "Low", "Close"]]


if __name__ == "__main__":
    # Quick manual test when run directly: python data_fetch.py
    print("Testing Bitcoin fetch...")
    try:
        btc = fetch_bitcoin_1h(days=2)
        print(f"Fetched {len(btc)} BTC candles. Latest: {btc.tail(3)}")
    except Exception as e:
        print(f"Bitcoin fetch failed: {e}")

    print("\nTesting Gold fetch (needs TWELVE_DATA_API_KEY env var)...")
    try:
        gold = fetch_gold_1h(outputsize=10)
        print(f"Fetched {len(gold)} Gold candles. Latest: {gold.tail(3)}")
    except Exception as e:
        print(f"Gold fetch failed: {e}")
