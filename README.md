# Gold & Bitcoin Signal Alerts

Hourly technical analysis on Gold (XAU/USD) and Bitcoin, pushed to your
phone. Runs free: Flask on Render, scheduled by cron-job.org, notifications
via Ntfy.

Built as a learning tool. It analyses and alerts — it does not trade, and
nothing here is financial advice.

## What an alert looks like

```
🟢 GOLD BUY signal

GOLD BUY
Signal triggered @ 4030.63 (2.1h ago)
Current price: 4048.20 (risen 0.4% since signal)
RSI: 35.7 | EMA20: 4026.60 | EMA50: 4083.37

Price has moved WITH this signal since it triggered.

🎯 Risk plan: stop 4026.10, target 4092.40 (2R) | ATR 14.73 (0.36% of
   price). Risking 22.10 per unit.
📅 October has averaged +1.77% over 66 years (rank 1/12 strongest month).
   Seasonal tailwind aligns with this signal.
🌍 Macro: dollar weakening (-0.31% over ~24h), which supports this BUY.
   Gold/DXY correlation -0.52 - holding as expected (inverse).
📐 Level 2 confluence: signal is near a support level (4026.58, tested
   multiple times).
🕯️ Level 3 confluence: bullish engulfing candle just formed.
```

## The analysis stack

| Layer | What it adds |
|---|---|
| **Level 1** (trigger) | RSI recovery from 30/70 extreme, confirmed by MACD |
| **Risk** | ATR-based stop, 2R target, per-unit risk |
| **Level 2** | Support/resistance clustering, Bollinger Bands |
| **Level 3** | Candlestick patterns, Fibonacci retracements |
| **Seasonality** | 65 years of monthly gold returns (gold only) |
| **Macro** | Dollar direction + whether gold/DXY is still transmitting |
| **Journal** | Every signal logged to Google Sheets for expectancy analysis |

Only Level 1 fires signals. Everything else is context, and every layer
fails soft — a broken enrichment never blocks an alert.

Signals are suppressed when they're more than 12 hours old (a stale
re-discovery after a restart) or when a FOMC/CPI/NFP release is within the
event window.

## Setup

**1. Get free API keys**
- [Twelve Data](https://twelvedata.com) — gold prices and DXY
- [CoinGecko](https://www.coingecko.com/en/api) — Demo plan, for Bitcoin
- Pick any hard-to-guess [Ntfy](https://ntfy.sh) topic, e.g. `gold-btc-a7x9k2`,
  and subscribe to it in the Ntfy mobile app

**2. Deploy on Render** — New Web Service, connect this repo:

```
Build Command:  pip install -r requirements.txt
Start Command:  gunicorn main:app --timeout 120
```

The `--timeout 120` matters. The default 30s kills workers mid-analysis.

**3. Environment variables**

```
TWELVE_DATA_API_KEY=...
COINGECKO_API_KEY=...
NTFY_TOPIC=...
PYTHON_VERSION=3.12.3
```

Python 3.12 is required — 3.14 breaks `pandas_ta`.

**4. Schedule it** on [cron-job.org](https://cron-job.org):

| Job | URL | Crontab |
|---|---|---|
| Alert trigger | `https://<your-app>.onrender.com/run` | `30 * * * *` |
| Keep-alive | `https://<your-app>.onrender.com/` | `5,15,25,35,45,55 * * * *` |

The keep-alive stops Render's free tier from sleeping. Without it, the
first hourly run after idle hits a cold-start splash page instead of the app.

**5. Optional — signal journal.** Follow the setup steps at the top of
`journal_logger.py`, then add `GOOGLE_SHEETS_ID` and
`GOOGLE_SERVICE_ACCOUNT`. Without these the journal fails silently and
alerts still send.

## Measuring whether it works

Only Level 1 fires signals, and its edge has never been measured. Two ways
to find out:

```bash
python backtest.py                 # replay history through the live rule
python backtest.py --candles 2000
```

Prints hit rate and expectancy in R, split by whether Level 2/3 confluence
was present, by signal direction, and by trading session. Writes
`backtest_results.csv`.

For live results, once the journal is running:

| Route | Purpose |
|---|---|
| `/backfill` | Resolve open journal rows to stop / target / timeout |
| `/stats` | Hit rate and expectancy from resolved rows |

Schedule `/backfill` daily on cron-job.org. Under ~30 trades, treat any
expectancy number as a hint rather than proof.

## Local development

```bash
pip install -r requirements.txt
export TWELVE_DATA_API_KEY=... COINGECKO_API_KEY=... NTFY_TOPIC=...
python main.py          # serves on :10000
curl localhost:10000/run
```

Individual modules are runnable for quick checks:

```bash
python data_fetch.py    # verify both price feeds
python seasonality.py   # verify the historical gold dataset
```

## Notes

- Bitcoin runs on 4-hour candles (CoinGecko's OHLC endpoint decides
  granularity), so it signals roughly a third as often as gold.
- Dedup state lives in a `state` tab of the journal's Google Sheet, so it
  survives Render restarts. Without Sheets credentials it falls back to
  `state.json` on Render's ephemeral disk, and the 12-hour staleness filter
  handles the fallout of a wipe.

See `CLAUDE.md` for architecture, the full list of known pitfalls, and the
roadmap.
