"""
Backtest harness - the thing that tells you whether any of this works.

Levels 1, 2 and 3 all rest on an assumption that has never been tested:
that the base rule has a positive edge. Waiting for the live journal to
accumulate 30 signals means waiting months at roughly 1.4 signals/week.
This replays historical candles through the exact same trigger function
the live app uses and answers the question immediately.

It also answers the more interesting question: does Level 2/3 confluence
actually improve outcomes, or does it just make notifications sound more
authoritative? Results are split by confluence present/absent and by
trading session so that stays an empirical question.

Trade simulation, per signal:
  entry  = close of the trigger candle
  stop   = entry -/+ 1.5 x ATR      (risk_analysis.py defaults)
  target = 2R
  Walk forward candle by candle. Stop hit -> -1R. Target hit -> +2R. If
  both fall inside the same candle we cannot know the order from OHLC, so
  we assume the STOP hit first - the conservative assumption, which keeps
  the result honest rather than flattering.
  Neither hit within max_hold candles -> mark to market at that close.

expectancy = mean R per trade. Positive means the rule has an edge on this
sample. Treat small samples with suspicion: 20 trades is a hint, not proof.

USAGE (needs TWELVE_DATA_API_KEY for live data):
    python backtest.py                  # gold, 5000 1h candles
    python backtest.py --candles 2000
"""

import argparse
import pandas as pd

from signals import add_indicators, get_signals_recovery
from risk_analysis import add_atr, DEFAULT_STOP_MULTIPLE, DEFAULT_TARGET_R
from level2_analysis import describe_level2_context
from level3_analysis import describe_level3_context
from session_context import classify_session

DEFAULT_MAX_HOLD = 48  # candles to wait before marking to market

NO_CONFLUENCE_MARKERS = ("No additional Level 2", "No additional Level 3")


def simulate_trade(
    df: pd.DataFrame,
    entry_idx: int,
    signal_type: str,
    max_hold: int = DEFAULT_MAX_HOLD,
) -> dict:
    """Walks a single signal forward and returns its R multiple and exit reason."""
    entry = df["Close"].iloc[entry_idx]
    atr = df["ATR"].iloc[entry_idx]
    if pd.isna(atr) or atr <= 0:
        return {}

    risk = DEFAULT_STOP_MULTIPLE * atr
    if signal_type == "BUY":
        stop, target = entry - risk, entry + risk * DEFAULT_TARGET_R
    else:
        stop, target = entry + risk, entry - risk * DEFAULT_TARGET_R

    window = df.iloc[entry_idx + 1 : entry_idx + 1 + max_hold]
    for _, bar in window.iterrows():
        if signal_type == "BUY":
            hit_stop = bar["Low"] <= stop
            hit_target = bar["High"] >= target
        else:
            hit_stop = bar["High"] >= stop
            hit_target = bar["Low"] <= target
        # Conservative: if both are inside one candle, assume the stop first.
        if hit_stop:
            return {"r": -1.0, "exit": "stop"}
        if hit_target:
            return {"r": float(DEFAULT_TARGET_R), "exit": "target"}

    if len(window) == 0:
        return {}
    exit_price = window["Close"].iloc[-1]
    r = (exit_price - entry) / risk if signal_type == "BUY" else (entry - exit_price) / risk
    return {"r": round(float(r), 3), "exit": "timeout"}


def run_backtest(df: pd.DataFrame, max_hold: int = DEFAULT_MAX_HOLD) -> pd.DataFrame:
    """
    Runs the live trigger over `df` and simulates every signal.
    Returns one row per trade with R multiple, confluence flag and session.
    """
    data = add_atr(add_indicators(df))
    signals = get_signals_recovery(data, rsi_oversold=30, rsi_overbought=70)
    if signals.empty:
        return pd.DataFrame()

    positions = {ts: i for i, ts in enumerate(data.index)}
    rows = []
    for _, sig in signals.iterrows():
        idx = positions.get(sig["time"])
        if idx is None or idx >= len(data) - 2:
            continue

        result = simulate_trade(data, idx, sig["type"], max_hold)
        if not result:
            continue

        history = data.iloc[: idx + 1]
        try:
            l2 = describe_level2_context(history, sig["price"], sig["type"])
            l3 = describe_level3_context(history, sig["price"])
        except Exception:
            l2 = l3 = ""
        has_confluence = not all(m in (l2 + l3) for m in NO_CONFLUENCE_MARKERS)

        rows.append(
            {
                "time": sig["time"],
                "type": sig["type"],
                "entry": round(float(sig["price"]), 2),
                "rsi": sig["rsi"],
                "r": result["r"],
                "exit": result["exit"],
                "confluence": has_confluence,
                "session": classify_session(sig["time"])["session"],
                "liquidity": classify_session(sig["time"])["liquidity"],
            }
        )
    return pd.DataFrame(rows)


def summarise(trades: pd.DataFrame, label: str = "ALL") -> str:
    """Hit rate, expectancy and average win/loss for a set of trades."""
    if trades.empty:
        return f"{label:<24} no trades"
    wins = trades[trades["r"] > 0]
    losses = trades[trades["r"] <= 0]
    win_rate = len(wins) / len(trades)
    expectancy = trades["r"].mean()
    avg_win = wins["r"].mean() if len(wins) else 0.0
    avg_loss = losses["r"].mean() if len(losses) else 0.0
    return (
        f"{label:<24} n={len(trades):<4} win={win_rate*100:5.1f}%  "
        f"expectancy={expectancy:+.3f}R  avg_win={avg_win:+.2f}R  avg_loss={avg_loss:+.2f}R"
    )


def report(trades: pd.DataFrame) -> None:
    """Prints the headline result plus the splits that actually matter."""
    if trades.empty:
        print("No trades generated - widen the candle range.")
        return

    print("\n" + "=" * 78)
    print(summarise(trades, "ALL TRADES"))
    print("-" * 78)
    print(summarise(trades[trades["confluence"]], "with L2/L3 confluence"))
    print(summarise(trades[~trades["confluence"]], "without confluence"))
    print("-" * 78)
    for sig_type in ("BUY", "SELL"):
        print(summarise(trades[trades["type"] == sig_type], sig_type))
    print("-" * 78)
    for liquidity in ("deepest", "good", "thin"):
        print(summarise(trades[trades["liquidity"] == liquidity], f"{liquidity} liquidity"))
    print("=" * 78)

    exits = trades["exit"].value_counts().to_dict()
    print(f"Exits: {exits}")
    print(
        "\nExpectancy is mean R per trade. Positive = edge on THIS sample.\n"
        "Under ~30 trades treat it as a hint, not proof. If the confluence\n"
        "split shows no improvement, Level 2/3 are decoration, not signal."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest the live signal rule on historical gold candles.")
    parser.add_argument("--candles", type=int, default=5000, help="how many 1h candles to request")
    parser.add_argument("--max-hold", type=int, default=DEFAULT_MAX_HOLD, help="candles before marking to market")
    args = parser.parse_args()

    from data_fetch import fetch_gold_1h

    print(f"Fetching {args.candles} gold candles...")
    df = fetch_gold_1h(outputsize=args.candles)
    print(f"Got {len(df)} candles: {df.index[0]} -> {df.index[-1]}")

    trades = run_backtest(df, max_hold=args.max_hold)
    report(trades)

    if not trades.empty:
        trades.to_csv("backtest_results.csv", index=False)
        print("\nPer-trade detail written to backtest_results.csv")
