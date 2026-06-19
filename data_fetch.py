"""
Fetches 1H candle data for Gold (XAU/USD) and Bitcoin (BTC/USD).

Gold    -> Twelve Data API (free tier, needs TWELVE_DATA_API_KEY env var)
Bitcoin -> CoinGecko API (free, no key needed)
"""

import os
import requests
import pandas as pd
from datetime import datetime, timezone


TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "")


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


def fetch_bitcoin_1h(days: int = 7) -> pd.DataFrame:
    """
    Fetches recent hourly BTC/USD prices from CoinGecko (free, no API key).
    CoinGecko's market_chart endpoint returns hourly granularity automatically
    when the range is <= 90 days.
    """
    url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
    params = {"vs_currency": "usd", "days": days}
    resp = requests.get(url, params=params, timeout=15)
    data = resp.json()

    if "prices" not in data:
        raise RuntimeError(f"CoinGecko error: {data}")

    rows = data["prices"]  # list of [timestamp_ms, price]
    df = pd.DataFrame(rows, columns=["timestamp", "Close"])
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("datetime").sort_index()
    return df[["Close"]]


if __name__ == "__main__":
    # Quick manual test when run directly: python data_fetch.py
    print("Testing Bitcoin fetch (no key needed)...")
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
