"""
Level 3 technical analysis: Candlestick patterns + Fibonacci retracements.

Implemented in plain pandas/numpy rather than via pandas-ta's cdl_pattern()
function, which requires the TA-Lib C library - that needs system-level
compilation and is known to be fragile on constrained free-tier hosting
(exactly the kind of dependency risk we hit repeatedly with pandas-ta
version mismatches earlier in this project). These pattern definitions are
well-established and simple enough to implement directly.

Candlestick patterns implemented:
  - Bullish/Bearish Engulfing
  - Hammer / Shooting Star
  - Doji

Fibonacci retracements: after a clear recent swing high and low, calculates
the 38.2%/50%/61.8% retracement levels and checks if current price is near
one of them.
"""

import pandas as pd
import numpy as np


def _candle_body(row) -> float:
    return abs(row["Close"] - row["Open"])


def _candle_range(row) -> float:
    return row["High"] - row["Low"]


def detect_engulfing(df: pd.DataFrame) -> str:
    """
    Checks the LAST TWO candles for a bullish or bearish engulfing pattern.
    Bullish engulfing: previous candle bearish (red), current candle bullish
    (green) and its body fully engulfs the previous candle's body.
    Bearish engulfing: the mirror image.
    Returns "bullish", "bearish", or "none".
    """
    if len(df) < 2:
        return "none"
    prev = df.iloc[-2]
    curr = df.iloc[-1]

    prev_bearish = prev["Close"] < prev["Open"]
    curr_bullish = curr["Close"] > curr["Open"]
    if (
        prev_bearish
        and curr_bullish
        and curr["Open"] <= prev["Close"]
        and curr["Close"] >= prev["Open"]
    ):
        return "bullish"

    prev_bullish = prev["Close"] > prev["Open"]
    curr_bearish = curr["Close"] < curr["Open"]
    if (
        prev_bullish
        and curr_bearish
        and curr["Open"] >= prev["Close"]
        and curr["Close"] <= prev["Open"]
    ):
        return "bearish"

    return "none"


def detect_hammer_or_shooting_star(df: pd.DataFrame, wick_to_body_ratio: float = 2.0) -> str:
    """
    Checks the LAST candle for a hammer (bullish reversal - long lower wick,
    small body, near the top of the range) or shooting star (bearish
    reversal - long upper wick, small body, near the bottom of the range).
    Returns "hammer", "shooting_star", or "none".
    """
    if len(df) < 1:
        return "none"
    row = df.iloc[-1]
    body = _candle_body(row)
    candle_range = _candle_range(row)

    if candle_range == 0 or body == 0:
        return "none"

    upper_wick = row["High"] - max(row["Open"], row["Close"])
    lower_wick = min(row["Open"], row["Close"]) - row["Low"]

    if lower_wick >= body * wick_to_body_ratio and upper_wick <= body * 0.5:
        return "hammer"
    if upper_wick >= body * wick_to_body_ratio and lower_wick <= body * 0.5:
        return "shooting_star"
    return "none"


def detect_doji(df: pd.DataFrame, body_to_range_threshold: float = 0.1) -> bool:
    """
    Checks the LAST candle for a doji - open and close very close together
    relative to the candle's full range, signaling indecision.
    """
    if len(df) < 1:
        return False
    row = df.iloc[-1]
    candle_range = _candle_range(row)
    if candle_range == 0:
        return False
    body = _candle_body(row)
    return (body / candle_range) <= body_to_range_threshold


def find_recent_swing(df: pd.DataFrame, lookback: int = 50) -> dict:
    """
    Finds the most recent significant swing high and swing low in the
    lookback window - the basis for Fibonacci retracement levels.
    """
    recent = df.tail(lookback)
    swing_high = recent["High"].max()
    swing_low = recent["Low"].min()
    swing_high_time = recent["High"].idxmax()
    swing_low_time = recent["Low"].idxmin()
    return {
        "swing_high": round(swing_high, 2),
        "swing_low": round(swing_low, 2),
        "swing_high_time": swing_high_time,
        "swing_low_time": swing_low_time,
    }


def calculate_fibonacci_levels(swing_high: float, swing_low: float) -> dict:
    """
    Calculates standard Fibonacci retracement levels between a swing high
    and swing low. Levels represent how far price has pulled back from the
    most recent extreme.
    """
    diff = swing_high - swing_low
    return {
        "0.0%": round(swing_high, 2),
        "23.6%": round(swing_high - diff * 0.236, 2),
        "38.2%": round(swing_high - diff * 0.382, 2),
        "50.0%": round(swing_high - diff * 0.5, 2),
        "61.8%": round(swing_high - diff * 0.618, 2),
        "100.0%": round(swing_low, 2),
    }


def describe_level3_context(df: pd.DataFrame, signal_price: float) -> str:
    """
    Produces a short, notification-ready description combining candlestick
    pattern detection on the most recent candle and Fibonacci retracement
    proximity, for use alongside a Level 1 signal.
    """
    notes = []

    engulfing = detect_engulfing(df)
    if engulfing != "none":
        notes.append(f"{engulfing} engulfing candle just formed")

    hammer_star = detect_hammer_or_shooting_star(df)
    if hammer_star == "hammer":
        notes.append("hammer candle (bullish reversal shape)")
    elif hammer_star == "shooting_star":
        notes.append("shooting star candle (bearish reversal shape)")

    if detect_doji(df):
        notes.append("doji candle (indecision)")

    swing = find_recent_swing(df)
    if swing["swing_high"] > swing["swing_low"]:  # sanity check there's an actual range
        fib_levels = calculate_fibonacci_levels(swing["swing_high"], swing["swing_low"])
        for level_name, level_price in fib_levels.items():
            if level_price == 0:
                continue
            distance_pct = abs(signal_price - level_price) / level_price * 100
            if distance_pct <= 0.5:
                notes.append(f"price is within 0.5% of the {level_name} Fibonacci retracement (${level_price})")
                break  # only mention the closest one

    if not notes:
        return "No additional Level 3 confluence (no notable candlestick pattern or Fibonacci level nearby)."

    return "Level 3 confluence: " + "; ".join(notes) + "."
