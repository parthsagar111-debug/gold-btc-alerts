# Gold + Bitcoin Signal Alert App

Checks Gold (XAU/USD) and Bitcoin (BTC/USD) and sends a push notification
(via Ntfy.sh) when a 3-indicator technical strategy (EMA20/50 + RSI + MACD)
aligns into a BUY or SELL signal. Also sends a daily status ping so you know
the app is alive even when no signal has fired.

This is a LEARNING tool. Expect roughly 2-5 signals per week combined across
both assets - some weeks zero, some weeks more. It is not a guaranteed-profit
system - treat every alert as a prompt to study the chart yourself, not as
financial advice.

---

## Files

- `signals.py`    - indicator math + signal detection logic
- `data_fetch.py` - pulls Gold (Twelve Data) and Bitcoin (CoinGecko) prices
- `notify.py`     - sends push alerts via Ntfy.sh
- `main.py`       - Flask web app; checks both assets when its /run URL is hit
- `requirements.txt` - Python dependencies
- `.python-version`  - pins Python to 3.12.3 (newer versions can break pandas-ta/numba)
- `state.json`    - auto-created at runtime; remembers the last alerted signal
                    so you don't get spammed every run for the same signal

---

## Why This Design (lessons learned while building it)

- **Render's dedicated "Cron Job" product is paid-only.** We deploy as a free
  **Web Service** instead, and use a free external scheduler (cron-job.org)
  to "ping" it every hour. This is a well-known, genuinely free workaround.
- **Render's free tier blocks outbound SMTP ports (25, 465, 587).** This means
  Gmail/SMTP-based email cannot work here - it will hang and crash the
  service. That's why this app uses Ntfy.sh only, which works over normal
  HTTPS (port 443), which Render does not block.
- **Render's default Python version can be too new for some libraries**
  (e.g. `numba`, a dependency of `pandas-ta`, doesn't support the very latest
  Python yet). The `.python-version` file pins a known-compatible version.

---

## Step 1 - Get Your Free Ntfy Topic (no signup needed)

1. Install the **ntfy** app on your phone (Play Store / App Store)
2. Pick a random, hard-to-guess topic name, e.g. `parth-gold-btc-9x4k2`
   (anyone who knows your topic name can see your alerts, so make it random)
3. In the ntfy app, tap **+** and subscribe to that exact topic name
4. That's it - no account needed

---

## Step 2 - Get a Free Twelve Data API Key (for Gold)

1. Go to twelvedata.com -> sign up free
2. Dashboard -> copy your API key
3. Keep it ready - you'll paste it into Render's dashboard, NOT into any code file
4. **Never paste API keys into chat or commit them to GitHub.** If a key is
   ever exposed accidentally, regenerate it immediately from the dashboard.

---

## Step 3 - Push This Code to GitHub

1. Create a new GitHub repo (e.g. `gold-btc-alerts`)
2. Upload all the files in this folder to it (drag-and-drop via
   "uploading an existing file" works fine - no git command line needed)

---

## Step 4 - Deploy on Render as a FREE Web Service

1. Go to render.com -> sign up/log in with GitHub
2. **New -> Web Service** (NOT Cron Job - that one is paid only)
3. Connect your `gold-btc-alerts` repo
4. Settings:
   - **Region:** Singapore (closest to India)
   - **Branch:** `main`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn main:app --timeout 120`
   - **Instance Type:** Free
5. Add Environment Variables (Render dashboard -> Environment tab):

   | Key | Value |
   |---|---|
   | TWELVE_DATA_API_KEY | your Twelve Data key |
   | NTFY_TOPIC | your chosen topic name |

   (If `PYTHON_VERSION` issues come up, also add `PYTHON_VERSION` = `3.12.3`
   as a belt-and-suspenders backup to the `.python-version` file.)

6. Click **Create Web Service**. Render gives you a URL like:
   `https://gold-btc-alerts-xxxx.onrender.com`

7. Visit that URL - you should see:
   `{"status": "alive", "message": "Gold/BTC alert service is running..."}`

---

## Step 5 - Set Up the Free Hourly Trigger (cron-job.org)

Render's free web services only act when something visits them - they don't
run on their own schedule. So we use a free external pinger:

1. Go to **cron-job.org** -> sign up (free, no card)
2. Click **Create cronjob**
3. **Title:** Gold BTC Alert Trigger
4. **URL:** `https://gold-btc-alerts-xxxx.onrender.com/run`
   (use YOUR actual Render URL + `/run`)
5. **Schedule:** Every hour
6. Save

Now cron-job.org hits your `/run` endpoint every hour, which triggers the
actual gold/bitcoin check and sends a push alert if a signal fires -
completely free, forever.

**Note on cold starts:** Render's free web services "sleep" after 15 minutes
of no traffic and take 30-60 seconds to wake up on the next request. This
means your hourly check might run a bit late sometimes - totally fine for an
hourly strategy.

---

## Step 6 - Test It

Before waiting for a real signal, confirm notifications work:

**https://your-app.onrender.com/test-notify**

This fires an immediate test push to your phone via Ntfy, independent of any
trading signal or schedule. If it doesn't arrive, double check:
- `NTFY_TOPIC` on Render matches EXACTLY what you subscribed to in the app
- You're actually subscribed to that topic in the ntfy app

Then check the real check works:

**https://your-app.onrender.com/run**

Returns JSON showing whether a signal fired for Gold/Bitcoin right now.
`null` for both just means no signal is active currently - that's normal,
not a bug.

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
- This strategy is intentionally simple (Level 1 of technical analysis) - good
  for learning pattern recognition, not a substitute for understanding the
  chart yourself
- Past signal frequency (simulated ~2-5/week) is not a guarantee of future
  frequency
- Free Render web services sleep after inactivity - the hourly cron-job.org
  ping wakes it back up, but there can be a short delay
