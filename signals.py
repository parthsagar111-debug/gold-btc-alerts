"""
Core signal logic — shared between backtest and live mode.

Strategy: Level 1 (EMA20/50 + RSI14 + MACD) "relaxed alignment" model.
BUY  -> EMA20 > EMA50  AND RSI < 50  AND MACD line > MACD signal line
SELL -> EMA20 < EMA50  AND RSI > 50  AND MACD line < MACD signal line

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


def get_signals(df: pd.DataFrame, cooldown_hours: int = 8) -> pd.DataFrame:
    """
    Walks through the dataframe and returns only NEW signal events
    (not every hour the condition happens to be true), respecting a cooldown.
    """
    signals = []
    last_time, last_type = None, None

    for idx, row in df.iterrows():
        buy = (row["EMA20"] > row["EMA50"]) and (row["RSI"] < 50) and (row["MACD"] > row["MACD_signal"])
        sell = (row["EMA20"] < row["EMA50"]) and (row["RSI"] > 50) and (row["MACD"] < row["MACD_signal"])

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
