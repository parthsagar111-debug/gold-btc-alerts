"""
ATR-based risk framing for signals.

A signal that says "consider buying" without a stop or target is not
actionable. This module turns a raw signal into a trade plan: where the
stop goes, where the target goes, and what the risk is in R terms.

ATR (Average True Range) is used rather than a fixed percentage because
gold at 0.3% daily range and gold at 1.2% daily range need different
stop distances for the same conviction. ATR adapts automatically.

Implemented in plain pandas - no pandas_ta - for the same reason Bollinger
Bands were rewritten: pandas_ta's numba-backed functions trigger a JIT
compilation cost on first call that caused a real WORKER TIMEOUT crash on
Render's free tier.
"""

import pandas as pd

DEFAULT_ATR_PERIOD = 14

# Stop and target are NOT arbitrary - they come from a grid search over 852
# trades on 10 years of real hourly XAU/USD (2012-2022), validated on a
# held-out second half. The original 1.5 x ATR / 2R pairing produced
# -0.040R expectancy (a losing system). Widening the stop is a monotonic
# improvement across the whole parameter neighbourhood, not a lone spike,
# which is consistent with the mechanical explanation: a 1.5 x ATR stop was
# being knocked out by noise before moves developed.
#
#   1.5 ATR / 2R, all sessions : -0.040R  (in -0.022 / out -0.060)
#   2.5 ATR / 3R, thin dropped : +0.113R  (in +0.089 / out +0.139)  <- this
#
# See CLAUDE.md "Backtest findings" before changing these.
DEFAULT_STOP_MULTIPLE = 2.5   # stop distance = 2.5 x ATR
DEFAULT_TARGET_R = 3.0        # target = 3x the risked distance (3R)


def add_atr(df: pd.DataFrame, period: int = DEFAULT_ATR_PERIOD) -> pd.DataFrame:
    """
    Adds an ATR column. True Range is the greatest of:
      high - low, |high - prev_close|, |low - prev_close|
    ATR is the rolling mean of True Range.
    Requires OHLC columns.
    """
    df = df.copy()
    prev_close = df["Close"].shift()
    true_range = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["ATR"] = true_range.rolling(window=period).mean()
    return df


def build_trade_plan(
    df: pd.DataFrame,
    entry_price: float,
    signal_type: str,
    stop_multiple: float = DEFAULT_STOP_MULTIPLE,
    target_r: float = DEFAULT_TARGET_R,
) -> dict:
    """
    Returns a trade plan dict for a signal, or {} if ATR isn't available
    (e.g. not enough candles yet).

    Direction matters: a BUY stops below entry and targets above; a SELL
    is the mirror.
    """
    df_atr = add_atr(df)
    atr = df_atr["ATR"].iloc[-1]
    if pd.isna(atr) or atr <= 0:
        return {}

    risk_distance = stop_multiple * atr
    if signal_type == "BUY":
        stop = entry_price - risk_distance
        target = entry_price + risk_distance * target_r
    else:
        stop = entry_price + risk_distance
        target = entry_price - risk_distance * target_r

    return {
        "atr": round(atr, 2),
        "atr_pct": round(atr / entry_price * 100, 2),
        "stop": round(stop, 2),
        "target": round(target, 2),
        "risk_per_unit": round(risk_distance, 2),
        "target_r": target_r,
    }


def position_size(account_risk_amount: float, risk_per_unit: float) -> float:
    """
    Fixed-fractional sizing: how many units to buy so that being stopped
    out costs exactly `account_risk_amount`.

    Example: risking 5000 INR with a risk_per_unit of 22.10 -> 226 units.
    Deliberately NOT wired into notifications - account size is personal
    and shouldn't live in this repo. Exposed for manual/journal use.
    """
    if risk_per_unit <= 0:
        return 0.0
    return round(account_risk_amount / risk_per_unit, 4)


def describe_trade_plan(plan: dict, signal_type: str) -> str:
    """One-line, notification-ready risk framing."""
    if not plan:
        return "Risk framing unavailable (not enough candles for ATR)."
    return (
        f"Risk plan: stop {plan['stop']}, target {plan['target']} "
        f"({plan['target_r']:.0f}R) | ATR {plan['atr']} ({plan['atr_pct']}% of price). "
        f"Risking {plan['risk_per_unit']} per unit."
    )
