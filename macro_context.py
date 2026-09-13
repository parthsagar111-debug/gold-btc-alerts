"""
Macro overlay for gold: the dollar, and whether the usual relationships
are currently holding.

Everything else in this project is derived from one input - past price.
Gold is a macro instrument: it moves on real yields, the dollar, and
official-sector flows. This module adds the cheapest and most reliable
macro input available on our existing data plan: the US Dollar Index.

Important caveat, deliberately encoded here rather than assumed: the
relationships are NOT stable. The real-rate model that explained most of
gold's variance for two decades explained very little of it after 2022,
when central bank buying and investment flows became the marginal price
setter. So this module does not just report DXY - it reports the rolling
correlation between gold and DXY, so you can see whether the dollar
channel is currently transmitting at all. A weak correlation means macro
context should be downweighted, not trusted.

CONTEXT ONLY. This never gates a signal. Fails soft - any error returns
an empty string and the alert still sends.
"""

import os
import requests
import pandas as pd

TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "")
CORRELATION_WINDOW = 60  # candles used for the rolling gold/DXY correlation


def fetch_dxy_1h(outputsize: int = 150) -> pd.DataFrame:
    """
    Fetches 1H US Dollar Index candles from Twelve Data.
    timezone=UTC is passed explicitly - Twelve Data defaults to
    America/New_York, which previously caused negative "hours ago" values
    in notifications when timestamps were mislabelled as UTC.
    """
    if not TWELVE_DATA_API_KEY:
        raise RuntimeError("TWELVE_DATA_API_KEY not set")

    resp = requests.get(
        "https://api.twelvedata.com/time_series",
        params={
            "symbol": "DXY",
            "interval": "1h",
            "outputsize": outputsize,
            "apikey": TWELVE_DATA_API_KEY,
            "timezone": "UTC",
        },
        timeout=15,
    )
    data = resp.json()
    if "values" not in data:
        raise RuntimeError(f"Twelve Data error (DXY): {data}")

    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    df = df.set_index("datetime").sort_index()
    df["Close"] = df["close"].astype(float)
    return df[["Close"]]


def describe_macro_context(gold_df: pd.DataFrame, signal_type: str) -> str:
    """
    Returns a notification-ready line describing dollar direction, whether
    it supports or opposes the signal, and how well the gold/DXY
    relationship is currently holding.
    """
    dxy = fetch_dxy_1h()
    if len(dxy) < 25:
        return ""

    latest = dxy["Close"].iloc[-1]
    day_ago = dxy["Close"].iloc[-25] if len(dxy) >= 25 else dxy["Close"].iloc[0]
    dxy_change_pct = (latest - day_ago) / day_ago * 100
    dollar_direction = "strengthening" if dxy_change_pct > 0 else "weakening"

    # Gold is priced in dollars: a stronger dollar is a headwind for gold,
    # so it supports a SELL and opposes a BUY.
    if signal_type == "BUY":
        supportive = dxy_change_pct < 0
    else:
        supportive = dxy_change_pct > 0
    stance = "supports" if supportive else "opposes"

    # Rolling correlation: is the dollar channel actually transmitting?
    joined = pd.merge_asof(
        gold_df[["Close"]].sort_index().reset_index().rename(columns={"Close": "gold"}),
        dxy.sort_index().reset_index().rename(columns={"Close": "dxy"}),
        on="datetime",
        direction="nearest",
    ).dropna()

    corr_note = ""
    if len(joined) >= CORRELATION_WINDOW:
        corr = (
            joined["gold"].pct_change().tail(CORRELATION_WINDOW)
            .corr(joined["dxy"].pct_change().tail(CORRELATION_WINDOW))
        )
        if pd.notna(corr):
            if corr < -0.3:
                strength = "holding as expected (inverse)"
            elif corr > 0.3:
                strength = "INVERTED from normal - unusual regime"
            else:
                strength = "weak right now, so treat this as low-information"
            corr_note = f" Gold/DXY correlation {corr:+.2f} - {strength}."

    return (
        f"Macro: dollar {dollar_direction} ({dxy_change_pct:+.2f}% over ~24h), "
        f"which {stance} this {signal_type}.{corr_note}"
    )
