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
    Fetches recent 1H XAU/USD candles from Twelve Data.
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
    df["Close"] = df["close"].astype(float)
    return df[["Close"]]


def fetch_bitcoin_1h(days: int = 4) -> pd.DataFrame:
    """
    Fetches recent hourly BTC/USD prices from CoinGecko.
    CoinGecko's market_chart endpoint returns hourly granularity automatically
    when the range is <= 90 days. We use 4 days (~96 candles) - just enough
    for EMA50 + MACD warmup, to minimize how much data we pull per call.

    Uses the free Demo plan API key (100 calls/min) via the
    x-cg-demo-api-key header. Falls back to the old no-key public endpoint
    if COINGECKO_API_KEY isn't set, though that's heavily rate-limited
    (5-15 calls/min, shared globally) and not recommended.
    """
    url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
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

    if "prices" not in data:
        raise RuntimeError(f"CoinGecko error: {data}")

    rows = data["prices"]  # list of [timestamp_ms, price]
    df = pd.DataFrame(rows, columns=["timestamp", "Close"])
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("datetime").sort_index()
    return df[["Close"]]


def fetch_usdinr_1h(outputsize: int = 150) -> pd.DataFrame:
    """
    Fetches recent 1H USD/INR candles from Twelve Data.
    Same API, same key as Gold USD - Twelve Data supports 140 currencies
    including INR, with forex data available 24/7 (no weekend gaps).
    """
    if not TWELVE_DATA_API_KEY:
        raise RuntimeError(
            "TWELVE_DATA_API_KEY environment variable not set. "
            "Set it in Render's Environment tab, never hardcode it."
        )

    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": "USD/INR",
        "interval": "1h",
        "outputsize": outputsize,
        "apikey": TWELVE_DATA_API_KEY,
    }
    resp = requests.get(url, params=params, timeout=15)
    data = resp.json()

    if "values" not in data:
        raise RuntimeError(f"Twelve Data error (USD/INR): {data}")

    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime").sort_index()
    df["Close"] = df["close"].astype(float)
    return df[["Close"]]


def fetch_gold_inr_1h(outputsize: int = 150) -> pd.DataFrame:
    """
    Fetches recent 1H Gold-in-INR candles from Twelve Data.
    Uses the symbol format Twelve Data documents for cross-rate calculation
    (e.g. XAU/INR), which computes Gold-in-Rupees on the fly from the
    underlying XAU/USD and USD/INR rates - no separate data source needed.
    """
    if not TWELVE_DATA_API_KEY:
        raise RuntimeError(
            "TWELVE_DATA_API_KEY environment variable not set. "
            "Set it in Render's Environment tab, never hardcode it."
        )

    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": "XAU/INR",
        "interval": "1h",
        "outputsize": outputsize,
        "apikey": TWELVE_DATA_API_KEY,
    }
    resp = requests.get(url, params=params, timeout=15)
    data = resp.json()

    if "values" not in data:
        raise RuntimeError(f"Twelve Data error (XAU/INR): {data}")

    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime").sort_index()
    df["Close"] = df["close"].astype(float)
    return df[["Close"]]


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

    print("\nTesting USD/INR fetch...")
    try:
        usdinr = fetch_usdinr_1h(outputsize=10)
        print(f"Fetched {len(usdinr)} USD/INR candles. Latest: {usdinr.tail(3)}")
    except Exception as e:
        print(f"USD/INR fetch failed: {e}")

    print("\nTesting Gold-INR (XAU/INR) fetch...")
    try:
        gold_inr = fetch_gold_inr_1h(outputsize=10)
        print(f"Fetched {len(gold_inr)} Gold-INR candles. Latest: {gold_inr.tail(3)}")
    except Exception as e:
        print(f"Gold-INR fetch failed: {e}")
