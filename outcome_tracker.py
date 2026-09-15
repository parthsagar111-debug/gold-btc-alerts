"""
Fills in journal outcomes so expectancy can be computed from live signals.

journal_logger.py writes every signal with `outcome`, `exit_price` and
`r_multiple` left blank. This walks back over those open rows, replays the
candles that have printed since each signal, and resolves them using the
same rules as backtest.py - so live results and backtested results are
directly comparable rather than being two different measurements.

Resolution per row:
    stop hit    -> -1R
    target hit  -> +2R
    both inside one candle -> stop assumed first (conservative; OHLC can't
                   tell us the order)
    neither, and older than MARK_TO_MARKET_HOURS -> marked to market
    neither, still young -> left open, retried next run

Triggered by GET /backfill (see main.py). Safe to call repeatedly; it only
touches rows whose outcome is still blank.
"""

import pandas as pd

from journal_logger import open_spreadsheet, HEADER_ROW

MARK_TO_MARKET_HOURS = 48


def _col(name: str) -> int:
    """1-based column index for a journal header name."""
    return HEADER_ROW.index(name) + 1


def _resolve(candles: pd.DataFrame, signal_type: str, entry: float, stop: float, target: float):
    """Returns (outcome, exit_price, r_multiple) or None if still unresolved."""
    risk = abs(entry - stop)
    if risk <= 0:
        return None

    for _, bar in candles.iterrows():
        if signal_type == "BUY":
            hit_stop, hit_target = bar["Low"] <= stop, bar["High"] >= target
        else:
            hit_stop, hit_target = bar["High"] >= stop, bar["Low"] <= target
        if hit_stop:
            return "stop", round(float(stop), 2), -1.0
        if hit_target:
            return "target", round(float(target), 2), 2.0
    return None


def backfill_outcomes() -> dict:
    """
    Resolves every open journal row it can. Returns a small summary dict
    suitable for returning from a Flask route.
    """
    from data_fetch import fetch_gold_1h, fetch_bitcoin_1h

    sheet = open_spreadsheet().sheet1
    rows = sheet.get_all_values()
    if len(rows) < 2:
        return {"checked": 0, "resolved": 0, "note": "journal empty"}

    candles = {}
    resolved = checked = 0

    for row_number, row in enumerate(rows[1:], start=2):
        record = dict(zip(HEADER_ROW, row + [""] * (len(HEADER_ROW) - len(row))))
        if record.get("outcome"):
            continue  # already resolved
        if not all(record.get(k) for k in ("asset", "signal_type", "signal_time_utc", "stop", "target")):
            continue

        checked += 1
        asset = record["asset"]
        if asset not in candles:
            candles[asset] = fetch_gold_1h() if asset == "GOLD" else fetch_bitcoin_1h()
        df = candles[asset]

        signal_time = pd.Timestamp(record["signal_time_utc"])
        if signal_time.tzinfo is None:
            signal_time = signal_time.tz_localize("UTC")
        else:
            signal_time = signal_time.tz_convert("UTC")

        after = df[df.index > signal_time]
        if after.empty:
            continue

        entry = float(record["signal_price"])
        stop = float(record["stop"])
        target = float(record["target"])
        outcome = _resolve(after, record["signal_type"], entry, stop, target)

        if outcome is None:
            age_hours = (pd.Timestamp.now(tz="UTC") - signal_time).total_seconds() / 3600
            if age_hours < MARK_TO_MARKET_HOURS:
                continue  # still open, try again next run
            exit_price = float(after["Close"].iloc[-1])
            risk = abs(entry - stop)
            r = (exit_price - entry) / risk if record["signal_type"] == "BUY" else (entry - exit_price) / risk
            outcome = ("timeout", round(exit_price, 2), round(float(r), 3))

        label, exit_price, r_multiple = outcome
        sheet.update_cell(row_number, _col("outcome"), label)
        sheet.update_cell(row_number, _col("exit_price"), exit_price)
        sheet.update_cell(row_number, _col("r_multiple"), r_multiple)
        resolved += 1

    return {"checked": checked, "resolved": resolved}


def expectancy_summary() -> dict:
    """
    Reads resolved rows and computes the numbers that decide whether any of
    this works: hit rate, expectancy in R, and the same split by whether
    Level 2/3 confluence was present.
    """
    sheet = open_spreadsheet().sheet1
    rows = sheet.get_all_values()
    if len(rows) < 2:
        return {"trades": 0}

    records = [dict(zip(HEADER_ROW, r + [""] * (len(HEADER_ROW) - len(r)))) for r in rows[1:]]
    resolved = [r for r in records if r.get("r_multiple") not in ("", None)]
    if not resolved:
        return {"trades": 0, "note": "no resolved trades yet - run /backfill"}

    df = pd.DataFrame(resolved)
    df["r_multiple"] = pd.to_numeric(df["r_multiple"], errors="coerce")
    df = df.dropna(subset=["r_multiple"])

    def stats(subset):
        if subset.empty:
            return None
        return {
            "trades": len(subset),
            "win_rate_pct": round((subset["r_multiple"] > 0).mean() * 100, 1),
            "expectancy_r": round(subset["r_multiple"].mean(), 3),
        }

    has_confluence = ~df["level2_context"].str.contains("No additional", na=False) | \
                     ~df["level3_context"].str.contains("No additional", na=False)

    return {
        "overall": stats(df),
        "with_confluence": stats(df[has_confluence]),
        "without_confluence": stats(df[~has_confluence]),
        "by_asset": {a: stats(df[df["asset"] == a]) for a in df["asset"].unique()},
        "caveat": "Under ~30 trades this is a hint, not proof.",
    }
