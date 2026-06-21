"""
Main entry point.

Runs as a tiny free web service on Render (since Render's dedicated Cron Job
product is paid-only, but Web Services have a real free tier). A free
external scheduler (cron-job.org) pings this service's /run URL every hour,
which triggers the actual check-and-alert logic below.

Each run:
  1. Fetches latest Gold + Bitcoin candles
  2. Computes indicators
  3. Checks if a NEW signal just fired (vs the last run)
  4. If yes -> sends a push notification via Ntfy
  5. Also sends one daily status ping at a fixed hour, even with no new signal

State (last signal seen) is persisted to a small JSON file so we don't
re-alert on every run for the same unchanged signal.
"""

import os
import json
import pandas as pd
from datetime import datetime, timezone
from flask import Flask, jsonify

from data_fetch import fetch_gold_1h, fetch_bitcoin_1h
from signals import add_indicators, get_signals, get_signals_recovery, current_status
from notify import notify_all

app = Flask(__name__)

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


def check_asset(name: str, fetch_fn, state: dict, state_key: str, signal_fn=get_signals, rsi_oversold: float = 50, rsi_overbought: float = 50) -> None:
    try:
        df = fetch_fn()
        df = add_indicators(df)

        # Log the actual fetched price every run, so Render's logs show real
        # data was retrieved - not just "no error occurred".
        snap = current_status(df)
        print(
            f"[{name}] price=${snap['price']:.2f} candle_time={snap['time']} "
            f"trend={snap['trend']} rsi={snap['rsi']} macd={snap['macd_state']}"
        )

        signals = signal_fn(df, cooldown_hours=8, rsi_oversold=rsi_oversold, rsi_overbought=rsi_overbought)

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

        # For Gold only: add historical seasonality context. Wrapped separately
        # so a seasonality fetch hiccup never delays or breaks the actual alert.
        if name == "GOLD":
            try:
                from seasonality import fetch_historical_gold, calculate_monthly_seasonality, describe_seasonality, check_alignment
                hist_df = fetch_historical_gold()
                summary = calculate_monthly_seasonality(hist_df)
                current_month = pd.Timestamp(latest["time"]).month
                seasonality_note = describe_seasonality(current_month, summary)
                alignment_note = check_alignment(latest["type"], current_month, summary)
                body += f"\n\n📅 {seasonality_note}\n{alignment_note}"
            except Exception as seasonality_error:
                print(f"[{name}] Seasonality enrichment failed (alert still sent OK): {seasonality_error}")

        notify_all(title, body, priority="high")
        state[state_key] = signal_id
        print(f"[{name}] New signal alerted: {latest['type']} @ {latest['price']:.2f}")

        # Log to the Signal Journal (Google Sheets) for later accuracy tracking.
        # Wrapped separately so a Sheets hiccup never breaks the actual alert.
        try:
            from journal_logger import log_signal_to_journal
            log_signal_to_journal(
                asset=name,
                signal_type=latest["type"],
                price=latest["price"],
                rsi=latest["rsi"],
                ema20=latest["ema20"],
                ema50=latest["ema50"],
                macd_state=current_status(df)["macd_state"],
            )
        except Exception as journal_error:
            print(f"[{name}] Journal logging failed (alert still sent OK): {journal_error}")

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


def run_check():
    print(f"=== Run at {datetime.now(timezone.utc).isoformat()} ===")
    state = load_state()

    check_asset("GOLD", fetch_gold_1h, state, "gold_last_signal", signal_fn=get_signals, rsi_oversold=50, rsi_overbought=50)
    check_asset("BTC", fetch_bitcoin_1h, state, "btc_last_signal", signal_fn=get_signals_recovery, rsi_oversold=30, rsi_overbought=70)
    maybe_send_daily_status(state)

    save_state(state)
    print("=== Run complete ===")
    return state


@app.route("/")
def home():
    """Simple landing page so Render's health check sees a 200 OK."""
    return jsonify({"status": "alive", "message": "Gold/BTC alert service is running. Hit /run to trigger a check."})


@app.route("/test-notify")
def test_notify_endpoint():
    """
    Sends an immediate test notification via Ntfy, regardless of signals
    or schedule. Use this to verify your NTFY_TOPIC is correct.
    """
    notify_all(
        "Test Alert",
        "If you see this on your phone, Ntfy is working correctly.",
        priority="default",
    )
    return jsonify({"status": "test notification sent", "time": datetime.now(timezone.utc).isoformat()})


@app.route("/run")
def run_endpoint():
    """
    This is the URL cron-job.org will ping every hour.
    Triggers the actual check-and-alert logic. Returns a minimal plain-text
    response (not full state) because cron-job.org's free tier aborts
    requests with overly large responses.
    """
    run_check()
    return "ok", 200


if __name__ == "__main__":
    # Render sets the PORT environment variable - we must listen on it.
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
