"""
Core signal logic — shared between backtest and live mode.

Strategy: Level 1 (EMA20/50 + RSI14 + MACD) "relaxed alignment" model.
BUY  -> EMA20 > EMA50  AND RSI < rsi_oversold   AND MACD line > MACD signal line
SELL -> EMA20 < EMA50  AND RSI > rsi_overbought AND MACD line < MACD signal line

RSI thresholds default to 50 (a simple midline split) but can be widened
per asset. Bitcoin's much higher volatility means RSI swings to extremes
more often than gold's - using 50 as the threshold for both can make
Bitcoin's signal fire on noise rather than a genuine momentum extreme.
Industry convention for volatile crypto assets is wider 30/70 bands instead
of the standard 30/70-on-extremes-only; here we use them as the BUY/SELL
threshold itself (not just "extreme" markers) to reduce false signals.

Only fires on a NEW signal (state change), with a cooldown to avoid spam.
"""

import pandas as pd
import pandas_ta as ta


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Adds EMA20, EMA50, RSI14, MACD line + signal line to a Close-price dataframe."""
    df = df.copy()
    df["EMA20"] = ta.ema(df["Close"], length=20)
    df["EMA50"] = ta.ema(df["Close"], length=50)
    df["RSI"] = ta.rsi(df["Close"], length=14)
    macd = ta.macd(df["Close"], fast=12, slow=26, signal=9)
    df["MACD"] = macd["MACD_12_26_9"]
    df["MACD_signal"] = macd["MACDs_12_26_9"]
    return df.dropna()


def get_signals(
    df: pd.DataFrame,
    cooldown_hours: int = 8,
    rsi_oversold: float = 50,
    rsi_overbought: float = 50,
) -> pd.DataFrame:
    """
    Walks through the dataframe and returns only NEW signal events
    (not every hour the condition happens to be true), respecting a cooldown.

    rsi_oversold / rsi_overbought default to 50 (gold's original simple
    midline check). Pass rsi_oversold=30, rsi_overbought=70 for a more
    volatility-appropriate threshold on assets like Bitcoin.
    """
    signals = []
    last_time, last_type = None, None

    for idx, row in df.iterrows():
        buy = (row["EMA20"] > row["EMA50"]) and (row["RSI"] < rsi_oversold) and (row["MACD"] > row["MACD_signal"])
        sell = (row["EMA20"] < row["EMA50"]) and (row["RSI"] > rsi_overbought) and (row["MACD"] < row["MACD_signal"])

        sig_type = "BUY" if buy else ("SELL" if sell else None)

        if sig_type:
            cooldown_passed = (
                last_time is None
                or (idx - last_time).total_seconds() / 3600 >= cooldown_hours
                or sig_type != last_type
            )
            if cooldown_passed:
                signals.append(
                    {
                        "time": idx,
                        "type": sig_type,
                        "price": row["Close"],
                        "rsi": round(row["RSI"], 1),
                        "ema20": round(row["EMA20"], 2),
                        "ema50": round(row["EMA50"], 2),
                    }
                )
                last_time, last_type = idx, sig_type

    return pd.DataFrame(signals)


def current_status(df: pd.DataFrame) -> dict:
    """Returns the latest indicator snapshot — used for the daily status ping."""
    row = df.iloc[-1]
    trend = "Bullish" if row["EMA20"] > row["EMA50"] else "Bearish"
    macd_state = "Bullish" if row["MACD"] > row["MACD_signal"] else "Bearish"
    return {
        "time": df.index[-1],
        "price": row["Close"],
        "trend": trend,
        "rsi": round(row["RSI"], 1),
        "macd_state": macd_state,
    }
