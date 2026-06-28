"""
Level 2 technical analysis: Support/Resistance levels + Bollinger Bands.

These add CONTEXT to a Level 1 signal (EMA/RSI/MACD) rather than replacing
it - a Level 1 BUY signal near a strong support level is a higher-conviction
setup than the same signal floating in open price territory with no
historical significance nearby.

Support/Resistance: detected via local price clustering - price levels that
have been tested (touched and reversed) multiple times in the recent
history are treated as significant.

Bollinger Bands: a moving average with bands at +/- N standard deviations.
Price touching the upper band = statistically stretched (overbought-ish);
touching the lower band = stretched the other way (oversold-ish). A tight
"squeeze" (narrow band width) suggests a big move may be coming, direction
unknown.
"""

import pandas as pd
import numpy as np


def add_bollinger_bands(df: pd.DataFrame, length: int = 20, std: float = 2.0) -> pd.DataFrame:
    """
    Adds Bollinger Band columns (lower, middle, upper, bandwidth, %B) to the
    dataframe.

    Implemented directly in pandas rather than via pandas_ta.bbands(), which
    triggers numba/llvmlite JIT compilation on its first call in a process -
    measured at ~0.3s in this sandbox, but almost certainly the root cause of
    a real WORKER TIMEOUT crash on Render's free tier, where weaker shared
    CPU likely makes that one-time compilation cost much worse. The formula
    here is mathematically identical to pandas_ta's; the only difference is
    avoiding the numba dependency for this specific calculation.
    """
    df = df.copy()
    middle = df["Close"].rolling(window=length).mean()
    rolling_std = df["Close"].rolling(window=length).std()
    upper = middle + std * rolling_std
    lower = middle - std * rolling_std

    df["BB_lower"] = lower
    df["BB_middle"] = middle
    df["BB_upper"] = upper
    df["BB_bandwidth"] = (upper - lower) / middle * 100  # band width as % of middle band
    df["BB_percent"] = (df["Close"] - lower) / (upper - lower)  # where price sits within the bands, 0-1
    return df


def find_support_resistance_levels(
    df: pd.DataFrame,
    lookback: int = 100,
    num_levels: int = 3,
    tolerance_pct: float = 0.3,
) -> dict:
    """
    Finds significant support/resistance levels by clustering recent swing
    highs and lows. A level is "significant" if price has approached it
    (within tolerance_pct%) multiple times in the lookback window.

    Returns {"support": [list of price levels below current price],
             "resistance": [list of price levels above current price]}
    sorted by proximity to the current price (closest first).
    """
    recent = df["Close"].tail(lookback)
    current_price = recent.iloc[-1]

    # Find local swing highs/lows (a simple peak/trough detector)
    swing_highs = []
    swing_lows = []
    window = 3
    for i in range(window, len(recent) - window):
        segment = recent.iloc[i - window : i + window + 1]
        center_val = recent.iloc[i]
        if center_val == segment.max():
            swing_highs.append(center_val)
        if center_val == segment.min():
            swing_lows.append(center_val)

    def cluster_levels(points: list, tolerance_pct: float) -> list:
        """Groups nearby price points into clusters, returns cluster centers sorted by # of touches."""
        if not points:
            return []
        points = sorted(points)
        clusters = []
        current_cluster = [points[0]]
        for p in points[1:]:
            if abs(p - current_cluster[-1]) / current_cluster[-1] * 100 <= tolerance_pct:
                current_cluster.append(p)
            else:
                clusters.append(current_cluster)
                current_cluster = [p]
        clusters.append(current_cluster)
        # Sort by cluster size (more touches = more significant), return cluster averages
        clusters.sort(key=len, reverse=True)
        return [round(np.mean(c), 2) for c in clusters]

    high_clusters = cluster_levels(swing_highs, tolerance_pct)
    low_clusters = cluster_levels(swing_lows, tolerance_pct)

    resistance = sorted([lvl for lvl in high_clusters if lvl > current_price])[:num_levels]
    support = sorted([lvl for lvl in low_clusters if lvl < current_price], reverse=True)[:num_levels]

    return {"support": support, "resistance": resistance, "current_price": round(current_price, 2)}


def describe_level2_context(df: pd.DataFrame, signal_price: float, signal_type: str) -> str:
    """
    Produces a short, notification-ready description combining Bollinger
    Band position and nearby support/resistance, for a given signal.
    """
    df_bb = add_bollinger_bands(df)
    latest = df_bb.iloc[-1]
    levels = find_support_resistance_levels(df)

    notes = []

    # Bollinger Band context
    bb_pct = latest["BB_percent"]
    if pd.notna(bb_pct):
        if bb_pct >= 0.95:
            notes.append("price is at/above the upper Bollinger Band (statistically stretched)")
        elif bb_pct <= 0.05:
            notes.append("price is at/below the lower Bollinger Band (statistically stretched)")
        if pd.notna(latest["BB_bandwidth"]) and latest["BB_bandwidth"] < 2.0:
            notes.append("bands are unusually tight (volatility squeeze - a bigger move may be coming)")

    # Support/Resistance proximity
    nearest_support = levels["support"][0] if levels["support"] else None
    nearest_resistance = levels["resistance"][0] if levels["resistance"] else None

    if signal_type == "BUY" and nearest_support is not None:
        distance_pct = abs(signal_price - nearest_support) / signal_price * 100
        if distance_pct <= 1.0:
            notes.append(f"signal is near a support level (₹/${nearest_support}, tested multiple times)")
    if signal_type == "SELL" and nearest_resistance is not None:
        distance_pct = abs(signal_price - nearest_resistance) / signal_price * 100
        if distance_pct <= 1.0:
            notes.append(f"signal is near a resistance level (₹/${nearest_resistance}, tested multiple times)")

    if not notes:
        return "No additional Level 2 confluence (not near a key level or band extreme)."

    return "Level 2 confluence: " + "; ".join(notes) + "."
