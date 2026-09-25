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

State (last signal seen) is persisted to the Google Sheet, with a local
JSON file as fallback, so we don't re-alert on every run for the same
unchanged signal. See state_store.py.
"""

import os
import pandas as pd
from datetime import datetime, timezone
from flask import Flask, jsonify, request

from data_fetch import fetch_gold_1h, fetch_bitcoin_1h
from signals import add_indicators, get_signals, get_signals_recovery, current_status
from notify import notify_all
from level2_analysis import describe_level2_context
from level3_analysis import describe_level3_context
from risk_analysis import build_trade_plan, describe_trade_plan
from event_filter import get_active_event, describe_event_risk, SUPPRESS_IN_WINDOW
from macro_context import describe_macro_context
from state_store import load_state, save_state
from session_context import describe_session, classify_session, SUPPRESS_THIN_SESSIONS

app = Flask(__name__)

DAILY_STATUS_HOUR = 9  # send a status ping once a day around 9am UTC-ish

# Staleness threshold for notifications. A genuinely fresh signal is at most
# ~2h old for gold (1h candles + hourly cron) and ~5h for bitcoin (4h candles),
# so anything older than this is a stale re-discovery - typically the result
# of a container restart wiping state.json (deploys, Render's documented
# "may restart at any time" free-tier behavior, spin-down/up cycles, or OOM
# kills), after which the next run re-finds whatever old signal still
# persists in the fetch window and would otherwise re-alert it as "new".
# Stale signals are recorded in state silently instead of notifying.
MAX_SIGNAL_AGE_HOURS = 12

# Gold WATCH tier: the same recovery rule with a looser RSI 45 threshold,
# sent as clearly lower-conviction alerts so the validated RSI 30 SIGNAL
# isn't diluted. Added because RSI 30 fires ~once a fortnight with dry
# spells of up to 73 days. The extra alerts are NOT a validated edge.
# Backtested at +0.036R (t = 0.74), -0.022 in-sample / +0.098
# out-of-sample, about +1.8/week. Tagged tier=WATCH in the journal so live
# data decides whether they're kept. See CLAUDE.md "WATCH tier".
WATCH_RSI_OVERSOLD = 45

# A WATCH alert within this many hours of a SIGNAL is the same move, so it
# is recorded silently rather than sent twice. Matches the 8h cooldown.
WATCH_DEDUP_HOURS = 8


def check_asset(
    name: str,
    fetch_fn,
    state: dict,
    state_key: str,
    signal_fn=get_signals,
    rsi_oversold: float = 50,
    rsi_overbought: float = 50,
    directions: tuple = ("BUY", "SELL"),
    tier: str = "SIGNAL",
    defer_to_key: str = "",
) -> None:
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

        try:
            signals = signal_fn(
                df, cooldown_hours=8, rsi_oversold=rsi_oversold,
                rsi_overbought=rsi_overbought, directions=directions,
            )
        except TypeError:
            # get_signals (the legacy midline rule) has no `directions` arg
            signals = signal_fn(df, cooldown_hours=8, rsi_oversold=rsi_oversold, rsi_overbought=rsi_overbought)

        if signals.empty:
            print(f"[{name}] No active signal.")
            return

        latest = signals.iloc[-1]
        signal_id = f"{latest['time']}_{latest['type']}"

        if state.get(state_key) == signal_id:
            print(f"[{name}] Latest signal already alerted. Skipping.")
            return

        # WATCH defers to the main SIGNAL tier: if a SIGNAL for this asset
        # fired within WATCH_DEDUP_HOURS, this is the same move - record
        # silently. state[defer_to_key] is "{time}_{type}" (see signal_id).
        if defer_to_key and state.get(defer_to_key):
            try:
                main_time = pd.Timestamp(state[defer_to_key].rsplit("_", 1)[0])
                watch_time = pd.Timestamp(latest["time"])
                if main_time.tzinfo is None:
                    main_time = main_time.tz_localize("UTC")
                if watch_time.tzinfo is None:
                    watch_time = watch_time.tz_localize("UTC")
                if abs((watch_time - main_time).total_seconds()) <= WATCH_DEDUP_HOURS * 3600:
                    state[state_key] = signal_id
                    print(f"[{name}] {tier} skipped - same move as SIGNAL at {main_time}.")
                    return
            except Exception as dedup_error:
                print(f"[{name}] {tier} dedup check failed (continuing): {dedup_error}")

        display_label = latest["type"]
        if tier == "WATCH":
            icon = "👀"
            title = f"{icon} {name} {display_label} watch (lower conviction)"
        else:
            icon = "🟢" if latest["type"] == "BUY" else "🔴"
            title = f"{icon} {name} {display_label} signal"

        # Compare the price NOW (snap, fetched at the top of this function)
        # against the price WHEN the signal triggered (latest, could be hours
        # earlier). This distinction was a source of real confusion - people
        # were reading the signal price as "the price to act at right now",
        # not realizing it's when the setup first formed, possibly hours ago.
        current_price = snap["price"]
        signal_price = latest["price"]
        pct_change = (current_price - signal_price) / signal_price * 100
        signal_time = pd.Timestamp(latest["time"])
        if signal_time.tzinfo is None:
            signal_time = signal_time.tz_localize("UTC")
        else:
            signal_time = signal_time.tz_convert("UTC")
        hours_ago = (pd.Timestamp.now(tz="UTC") - signal_time).total_seconds() / 3600

        # Staleness filter: if the signal is older than the threshold, this is
        # a re-discovery after a state wipe, not an actionable fresh setup.
        # Record it in state (so it never re-fires) but do NOT notify.
        if hours_ago > MAX_SIGNAL_AGE_HOURS:
            state[state_key] = signal_id
            print(
                f"[{name}] Latest signal is {hours_ago:.1f}h old "
                f"(> {MAX_SIGNAL_AGE_HOURS}h threshold) - recorded silently, not notifying."
            )
            return

        # Favorable direction depends on signal type: a BUY wants price to have
        # RISEN since the signal (so current REQUIRES SUBSEQUENT favorable
        # confirmation), a SELL wants price to have FALLEN. If it moved the
        # opposite way, the original thesis may already be weakening.
        if latest["type"] == "BUY":
            moved_favorably = pct_change > 0
        else:
            moved_favorably = pct_change < 0

        direction_word = "risen" if pct_change > 0 else ("fallen" if pct_change < 0 else "stayed flat")
        favorable_note = (
            "Price has moved WITH this signal since it triggered - the setup is still tracking as expected."
            if moved_favorably
            else "Price has moved AGAINST this signal since it triggered - the original setup may be weakening. "
                 "Check current indicators (not just this alert) before acting."
        )

        # Event risk gate. Gold's largest single-day moves cluster around
        # FOMC / CPI / NFP releases, so a technical setup inside one of those
        # windows is mostly noise. Recorded in state either way so it can't
        # re-fire later as "new".
        active_event = ""
        try:
            active_event = get_active_event()
        except Exception as event_error:
            print(f"[{name}] Event filter failed (continuing without it): {event_error}")

        if active_event and SUPPRESS_IN_WINDOW:
            state[state_key] = signal_id
            print(f"[{name}] Signal suppressed - inside event window ({active_event}).")
            return

        body = (
            f"{name} {display_label}\n"
            f"Signal triggered @ {signal_price:.2f} ({hours_ago:.1f}h ago)\n"
            f"Current price: {current_price:.2f} ({direction_word} {abs(pct_change):.1f}% since signal)\n"
            f"RSI: {latest['rsi']} | EMA20: {latest['ema20']} | EMA50: {latest['ema50']}\n\n"
            f"{favorable_note}"
        )
        if tier == "WATCH":
            body = (
                f"WATCH tier: RSI recovered through {rsi_oversold:g}, not the validated 30. "
                f"Backtested near breakeven - context, not a trade signal.\n\n" + body
            )

        # Every enrichment below is wrapped individually and fails soft: a
        # single broken layer must never block the alert itself. Notes are
        # also captured into variables so the journal can record exactly
        # what context was present at signal time.
        seasonality_note = ""
        level2_note = ""
        level3_note = ""
        macro_note = ""
        plan = {}

        # ATR risk framing: turns "consider buying" into an actual trade plan.
        try:
            plan = build_trade_plan(df, entry_price=current_price, signal_type=latest["type"])
            body += f"\n\n🎯 {describe_trade_plan(plan, latest['type'])}"
        except Exception as risk_error:
            print(f"[{name}] Risk framing failed (alert still sent OK): {risk_error}")

        # Session context. Annotates only - see session_context.py for why
        # this deliberately does not gate.
        session_note = ""
        try:
            session_info = classify_session(signal_time)
            session_note = describe_session(signal_time)
            # Thin sessions backtested at -0.144R (t = -1.98) - the only
            # statistically significant finding in the run. Recorded in
            # state either way so it can't re-fire later as "new".
            if session_info["liquidity"] == "thin" and SUPPRESS_THIN_SESSIONS:
                state[state_key] = signal_id
                print(f"[{name}] Signal suppressed - thin session ({session_info['session']}).")
                return
            if session_info["liquidity"] == "thin":
                body += f"\n\n\U0001F317 {session_note}"
        except Exception as session_error:
            print(f"[{name}] Session context failed (alert still sent OK): {session_error}")

        # For Gold only: historical seasonality context.
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

        # Macro overlay: dollar direction plus whether the gold/DXY
        # relationship is currently transmitting at all.
        try:
            macro_note = describe_macro_context(df, signal_type=latest["type"])
            if macro_note:
                body += f"\n\n🌍 {macro_note}"
        except Exception as macro_error:
            print(f"[{name}] Macro context failed (alert still sent OK): {macro_error}")

        # Level 2: Support/Resistance + Bollinger Bands.
        try:
            level2_note = describe_level2_context(df, signal_price=signal_price, signal_type=latest["type"])
            body += f"\n\n📐 {level2_note}"
        except Exception as level2_error:
            print(f"[{name}] Level 2 enrichment failed (alert still sent OK): {level2_error}")

        # Level 3: Candlestick patterns + Fibonacci retracements.
        try:
            level3_note = describe_level3_context(df, signal_price=signal_price)
            body += f"\n\n🕯️ {level3_note}"
        except Exception as level3_error:
            print(f"[{name}] Level 3 enrichment failed (alert still sent OK): {level3_error}")

        # Event annotation (only reached when SUPPRESS_IN_WINDOW is False).
        if active_event:
            body += f"\n\n⚠️ {describe_event_risk(active_event)}"

        notify_all(title, body, priority="default" if tier == "WATCH" else "high")
        state[state_key] = signal_id
        print(f"[{name}] New {tier} alerted: {latest['type']} @ {latest['price']:.2f}")

        # Signal journal. This is what makes the whole system measurable -
        # without it there is no hit rate and no expectancy, and the Level 2/3
        # layers rest on an untested assumption. Fails soft.
        try:
            from journal_logger import log_signal_to_journal
            log_signal_to_journal(
                asset=name,
                signal_type=latest["type"],
                signal_time_utc=str(latest["time"]),
                signal_price=signal_price,
                price_now=current_price,
                hours_old=round(hours_ago, 1),
                rsi=latest["rsi"],
                ema20=latest["ema20"],
                ema50=latest["ema50"],
                macd_state=snap["macd_state"],
                atr=plan.get("atr", ""),
                stop=plan.get("stop", ""),
                target=plan.get("target", ""),
                risk_per_unit=plan.get("risk_per_unit", ""),
                level2_context=level2_note,
                level3_context=level3_note,
                seasonality=seasonality_note,
                macro=macro_note,
                event_risk=active_event,
                notes=session_note,
                tier=tier,
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

    # SIGNAL and WATCH both read gold; fetch once per run to spare the
    # Twelve Data rate limit. Lazy, so a fetch failure still fails soft
    # inside check_asset's try.
    gold_cache = {}

    def fetch_gold_once():
        if "df" not in gold_cache:
            gold_cache["df"] = fetch_gold_1h()
        return gold_cache["df"].copy()

    # Gold is BUY-only - see CLAUDE.md "Backtest findings". Bitcoin keeps
    # both directions because it has never been backtested; do not assume
    # the gold result transfers to it.
    check_asset("GOLD", fetch_gold_once, state, "gold_last_signal", signal_fn=get_signals_recovery,
                rsi_oversold=30, rsi_overbought=70, directions=("BUY",))
    # Must run after the SIGNAL check above so its dedup sees this run's SIGNAL.
    check_asset("GOLD", fetch_gold_once, state, "gold_last_watch", signal_fn=get_signals_recovery,
                rsi_oversold=WATCH_RSI_OVERSOLD, rsi_overbought=70, directions=("BUY",),
                tier="WATCH", defer_to_key="gold_last_signal")
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


@app.route("/backtest")
def backtest_endpoint():
    """
    Runs the backtest on Render, where pandas_ta and the API key already
    exist - no local install needed. Open in a browser.

    Query params:
        ?candles=5000   how much history to replay (default 5000)
        ?max_hold=48    candles before marking a trade to market

    Measured at ~3s for 5000 candles on free-tier CPU, comfortably inside
    gunicorn's 120s timeout. This is the only route that returns a large
    response - never point a cron-job.org job at it (response size cap).
    """
    try:
        from backtest import run_backtest, summarise
        from data_fetch import fetch_gold_1h

        candles = min(int(request.args.get("candles", 5000)), 5000)
        max_hold = int(request.args.get("max_hold", 48))

        df = fetch_gold_1h(outputsize=candles)
        trades = run_backtest(df, max_hold=max_hold)
        if trades.empty:
            return jsonify({"trades": 0, "note": "no signals in this range - try more candles"})

        def block(subset):
            if subset.empty:
                return None
            return {
                "trades": len(subset),
                "win_rate_pct": round((subset["r"] > 0).mean() * 100, 1),
                "expectancy_r": round(subset["r"].mean(), 3),
            }

        return jsonify({
            "period": {"from": str(df.index[0]), "to": str(df.index[-1]), "candles": len(df)},
            "overall": block(trades),
            "with_confluence": block(trades[trades["confluence"]]),
            "without_confluence": block(trades[~trades["confluence"]]),
            "by_direction": {t: block(trades[trades["type"] == t]) for t in trades["type"].unique()},
            "by_liquidity": {l: block(trades[trades["liquidity"] == l]) for l in trades["liquidity"].unique()},
            "exits": trades["exit"].value_counts().to_dict(),
            "summary_line": summarise(trades, "ALL"),
            "caveat": "Expectancy is mean R per trade. Under ~30 trades treat it as a hint, not proof.",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/backfill")
def backfill_endpoint():
    """
    Resolves open journal rows (stop/target/timeout) so expectancy can be
    computed. Safe to call repeatedly - only touches unresolved rows.
    Schedule this daily on cron-job.org once the journal is live.
    """
    try:
        from outcome_tracker import backfill_outcomes
        return jsonify(backfill_outcomes())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/stats")
def stats_endpoint():
    """Hit rate and expectancy from resolved journal rows."""
    try:
        from outcome_tracker import expectancy_summary
        return jsonify(expectancy_summary())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
