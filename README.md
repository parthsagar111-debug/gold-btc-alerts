# Gold + Bitcoin Signal Alert App

Checks Gold (XAU/USD) and Bitcoin (BTC/USD) every hour using a 3-indicator
strategy (EMA20/50 crossover state + RSI + MACD). Sends you a push notification
(Ntfy.sh) and email when all 3 align — and a daily status ping even if nothing fires.

This is a LEARNING tool. Expect roughly 2-5 signals per week combined across
both assets. It is not a guaranteed-profit system - treat every alert as a
prompt to go study the chart yourself, not as financial advice.

---

## Files

- `signals.py`    - indicator math + signal detection logic
- `data_fetch.py` - pulls Gold (Twelve Data) and Bitcoin (CoinGecko) prices
- `notify.py`     - sends alerts via Ntfy.sh and Gmail
- `main.py`       - runs once, checks both assets, fires alerts if needed
- `state.json`    - auto-created; remembers the last alerted signal so you
                    don't get spammed every hour for the same signal

---

## Step 1 - Get Your Free Accounts/Keys Ready

### A) Twelve Data API key (for Gold)
1. Go to twelvedata.com -> sign up free
2. Dashboard -> copy your API key
3. Keep it ready - you'll paste it into Render's dashboard, NOT into any code file

### B) Ntfy.sh topic (for push notifications - no signup needed)
1. Install the "ntfy" app on your phone (Play Store / App Store), OR just use ntfy.sh in browser
2. Pick a random, hard-to-guess topic name, e.g. `parth-gold-btc-9x4k2`
   (anyone who knows your topic name can see your alerts, so make it random)
3. In the ntfy app, tap "+" and subscribe to that exact topic name
4. That's it - no account needed

### C) Gmail App Password (for email backup)
1. Your Gmail account needs 2-Step Verification turned on (Google Account -> Security)
2. Go to myaccount.google.com/apppasswords
3. Create an app password for "Mail" - copy the 16-character password
4. This is DIFFERENT from your normal Gmail password - use only this one here

---

## Step 2 - Push This Code to GitHub

Same flow as PMHunt:
1. Create a new GitHub repo (e.g. `gold-btc-alerts`)
2. Upload these files to it (or `git push` if you're comfortable with git)

---

## Step 3 - Deploy on Render as a Cron Job

1. Go to render.com -> sign up/log in with GitHub
2. New -> Cron Job
3. Connect your `gold-btc-alerts` repo
4. Settings:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python main.py`
   - **Schedule:** `0 * * * *`   (runs at the top of every hour)
5. Add Environment Variables (Render dashboard -> Environment tab):

   | Key | Value |
   |---|---|
   | TWELVE_DATA_API_KEY | your Twelve Data key |
   | NTFY_TOPIC | your chosen topic name |
   | GMAIL_ADDRESS | your Gmail address |
   | GMAIL_APP_PASSWORD | the 16-character app password |
   | NOTIFY_EMAIL_TO | where you want alerts emailed (can be same Gmail) |

6. Deploy. Render will run `main.py` once an hour automatically.

---

## Step 4 - Test It Works

Before waiting for a real signal, test notifications manually:

```bash
python notify.py
```

This sends a test message to both Ntfy and Email. If you get it on your phone
and in your inbox, the pipes are connected correctly.

---

## What Counts as a "Signal"

```
BUY  -> EMA20 > EMA50  AND  RSI < 50  AND  MACD line > MACD signal line
SELL -> EMA20 < EMA50  AND  RSI > 50  AND  MACD line < MACD signal line
```

Only fires once per new signal (not every hour it stays true), with an 8-hour
cooldown before the same direction can fire again.

---

## Honest Limitations

- Free Twelve Data tier = ~1 min delay, 800 calls/day limit (we use ~24/day, fine)
- CoinGecko free tier has no key but can occasionally rate-limit during high traffic
- This strategy is intentionally simple (Level 1 in our discussion) - good for
  learning pattern recognition, not a substitute for understanding the chart yourself
- Past signal frequency (simulated ~2-5/week) is not a guarantee of future frequency
