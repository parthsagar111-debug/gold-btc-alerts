"""
Gold seasonality analysis - inspired by Forecaster.biz's methodology.

Fetches 65+ years of monthly gold price history (free, no API key, via
freegoldapi.com) and calculates:
  1. Average historical return by calendar month (seasonality)
  2. Detrended Price Oscillator (DPO) on the seasonal curve, to highlight
     likely cyclical turning points rather than just average direction

This is a SEPARATE signal from the Level 1 technical strategy (EMA/RSI/MACD).
The idea, per Forecaster's own stated approach: seasonality tells you the
broader historical tendency for "around now", while the technical signal
tells you the precise timing. When they agree, conviction is higher; when
they disagree, that's worth extra scrutiny rather than blind action.

Data source note: pre-1960 data is annual only (too sparse for monthly
seasonality), 1960-2024 is monthly (World Bank), 2025+ is daily (Yahoo).
We use 1960-onward for genuine month-level seasonality - that's 65+ years,
statistically solid for a calendar-month average.
"""

import pandas as pd
import requests
from io import StringIO

FREEGOLDAPI_CSV_URL = "https://freegoldapi.com/data/latest.csv"
SEASONALITY_START_YEAR = 1960  # earliest year with reliable monthly granularity


def fetch_historical_gold() -> pd.DataFrame:
    """
    Downloads the full historical gold price CSV (date, price, source) and
    filters to the monthly-or-better era (1960+).
    """
    resp = requests.get(FREEGOLDAPI_CSV_URL, timeout=20)
    resp.raise_for_status()

    df = pd.read_csv(StringIO(resp.text))
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"].dt.year >= SEASONALITY_START_YEAR].copy()
    df = df.sort_values("date").reset_index(drop=True)
    return df


def calculate_monthly_seasonality(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each calendar month (Jan-Dec), calculates the average month-over-month
    % return across all historical years. This is the core "seasonality"
    metric - e.g. "October has historically averaged +1.8%".

    Returns a DataFrame indexed by month number (1-12) with columns:
      avg_return_pct, years_of_data, rank (1 = strongest month)
    """
    monthly = df.set_index("date")["price"].resample("MS").last().dropna()
    monthly_returns = monthly.pct_change().dropna() * 100

    by_month = monthly_returns.groupby(monthly_returns.index.month)
    summary = by_month.agg(["mean", "count"]).rename(columns={"mean": "avg_return_pct", "count": "years_of_data"})
    summary["avg_return_pct"] = summary["avg_return_pct"].round(2)
    summary["rank"] = summary["avg_return_pct"].rank(ascending=False).astype(int)
    summary.index.name = "month"
    return summary.sort_index()


def calculate_dpo(monthly_prices: pd.Series, period: int = 12) -> pd.Series:
    """
    Detrended Price Oscillator: price minus a displaced simple moving average.
    Strips out the long-term trend to reveal shorter recurring cycles,
    helping identify likely turning points rather than just direction.

    Standard formula: DPO = Price[today] - SMA(period)[period/2 + 1 days ago]
    """
    sma = monthly_prices.rolling(window=period).mean()
    shift_amount = int(period / 2) + 1
    dpo = monthly_prices - sma.shift(shift_amount)
    return dpo


def get_seasonality_for_month(month: int, summary: pd.DataFrame) -> dict:
    """Returns the seasonality stats for a specific calendar month (1-12)."""
    if month not in summary.index:
        return {"avg_return_pct": None, "rank": None, "years_of_data": 0}
    row = summary.loc[month]
    return {
        "avg_return_pct": float(row["avg_return_pct"]),
        "rank": int(row["rank"]),
        "years_of_data": int(row["years_of_data"]),
    }


def describe_seasonality(month: int, summary: pd.DataFrame) -> str:
    """
    Produces a short human-readable seasonality blurb for use in
    notifications, e.g. "October has averaged +1.8% over 65 years
    (6th strongest month)".
    """
    stats = get_seasonality_for_month(month, summary)
    if stats["avg_return_pct"] is None:
        return "Seasonality data unavailable for this month."

    month_name = pd.Timestamp(2000, month, 1).strftime("%B")
    direction = "averaged" if stats["avg_return_pct"] >= 0 else "averaged"
    sign = "+" if stats["avg_return_pct"] >= 0 else ""
    return (
        f"{month_name} has {direction} {sign}{stats['avg_return_pct']}% over "
        f"{stats['years_of_data']} years (rank {stats['rank']}/12 strongest month)."
    )


def check_alignment(signal_type: str, month: int, summary: pd.DataFrame) -> str:
    """
    Compares a technical signal (BUY/SELL) against seasonality for the
    current month, and returns a short note on whether they agree or
    conflict - directly inspired by Forecaster's "seasonality + technicals"
    combination approach.
    """
    stats = get_seasonality_for_month(month, summary)
    if stats["avg_return_pct"] is None:
        return ""

    seasonally_bullish = stats["avg_return_pct"] > 0

    if signal_type == "BUY" and seasonally_bullish:
        return "Seasonal tailwind aligns with this signal."
    elif signal_type == "SELL" and not seasonally_bullish:
        return "Seasonal tailwind aligns with this signal."
    elif signal_type == "BUY" and not seasonally_bullish:
        return "This goes AGAINST the seasonal trend - worth extra scrutiny."
    elif signal_type == "SELL" and seasonally_bullish:
        return "This goes AGAINST the seasonal trend - worth extra scrutiny."
    return ""


if __name__ == "__main__":
    # Manual test: python seasonality.py
    print("Fetching historical gold data...")
    df = fetch_historical_gold()
    print(f"Loaded {len(df)} records from {df['date'].min().date()} to {df['date'].max().date()}")

    summary = calculate_monthly_seasonality(df)
    print("\nMonthly seasonality summary:")
    print(summary)

    print("\nExample descriptions:")
    for m in [1, 6, 10, 11]:
        print(f"  Month {m}: {describe_seasonality(m, summary)}")

    print("\nExample alignment checks:")
    print(f"  BUY in October: {check_alignment('BUY', 10, summary)}")
    print(f"  SELL in October: {check_alignment('SELL', 10, summary)}")
