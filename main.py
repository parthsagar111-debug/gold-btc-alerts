"""
Main entry point. Designed to be run once per hour by a scheduler (Render Cron Job).

Each run:
  1. Fetches latest Gold + Bitcoin candles
  2. Computes indicators
  3. Checks if a NEW signal just fired (vs the last run)
  4. If yes -> sends notification via Ntfy + Email
  5. Also sends one daily status ping at a fixed hour, even with no new signal

State (last signal seen) is persisted to a small JSON file so we don't
re-alert on every run for the same unchanged signal.
"""

import os
import json
from datetime import datetime, timezone

from data_fetch import fetch_gold_1h, fetch_bitcoin_1h
from signals import add_indicators, get_signals, current_status
from notify import notify_all

STATE_FILE = "state.json"
DAILY_STATUS_HOUR = 9  # send a status ping once a day around 9am UTC-ish


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"gold_last_signal": None, "btc_last_signal": None, "last_status_date": None}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, default=str)


def check_asset(name: str, fetch_fn, state: dict, state_key: str) -> None:
    try:
        df = fetch_fn()
        df = add_indicators(df)
        signals = get_signals(df, cooldown_hours=8)

        if signals.empty:
            print(f"[{name}] No active signal.")
            return

        latest = signals.iloc[-1]
        signal_id = f"{latest['time']}_{latest['type']}"

        if state.get(state_key) == signal_id:
            print(f"[{name}] Latest signal already alerted. Skipping.")
            return

        icon = "🟢" if latest["type"] == "BUY" else "🔴"
        title = f"{icon} {name} {latest['type']} signal"
        body = (
            f"{name} {latest['type']} @ ${latest['price']:.2f}\n"
            f"RSI: {latest['rsi']} | EMA20: {latest['ema20']} | EMA50: {latest['ema50']}\n"
            f"Time: {latest['time']}\n\n"
            f"All 3 indicators aligned. Check the chart before acting."
        )
        notify_all(title, body, priority="high")
        state[state_key] = signal_id
        print(f"[{name}] New signal alerted: {latest['type']} @ {latest['price']:.2f}")

    except Exception as e:
        print(f"[{name}] ERROR: {e}")


def maybe_send_daily_status(state: dict) -> None:
    """Sends one status ping per day so you know the app is alive even with no signal."""
    today = datetime.now(timezone.utc).date().isoformat()
    now_hour = datetime.now(timezone.utc).hour

    if state.get("last_status_date") == today or now_hour != DAILY_STATUS_HOUR:
        return

    lines = ["📊 Daily Status\n"]
    for name, fetch_fn in [("GOLD", fetch_gold_1h), ("BTC", fetch_bitcoin_1h)]:
        try:
            df = add_indicators(fetch_fn())
            s = current_status(df)
            lines.append(
                f"{name}: ${s['price']:.2f} | Trend: {s['trend']} | RSI: {s['rsi']} | MACD: {s['macd_state']}"
            )
        except Exception as e:
            lines.append(f"{name}: error fetching ({e})")

    notify_all("📊 Daily Gold/BTC Status", "\n".join(lines), priority="low")
    state["last_status_date"] = today


def main():
    print(f"=== Run at {datetime.now(timezone.utc).isoformat()} ===")
    state = load_state()

    check_asset("GOLD", fetch_gold_1h, state, "gold_last_signal")
    check_asset("BTC", fetch_bitcoin_1h, state, "btc_last_signal")
    maybe_send_daily_status(state)

    save_state(state)
    print("=== Run complete ===")


if __name__ == "__main__":
    main()
