# CLAUDE.md — Gold & Bitcoin Signal Alert System

Context for Claude Code. Read this fully before changing anything. Much of
what follows is trial-and-error that cost real debugging time; the
"Gotchas" section in particular exists so those bugs are never reintroduced.

---

## What this is

A Flask app that checks Gold (XAU/USD) and Bitcoin hourly for technical
setups and pushes alerts to a phone via Ntfy. Built as a learning tool and
a portfolio piece — **not** a trading system, and it places no orders.

Owner: Parth, Senior PM based in Mumbai. Also serves as an interview
talking point, so design decisions should be defensible and evidence-based
rather than arbitrary.

**There is no LLM anywhere in this codebase.** Every computation is
deterministic pandas/numpy. Don't add an AI dependency without being asked.

---

## Architecture

```
cron-job.org  --hourly-->  Render (Flask) /run
                                |
                    +-----------+-----------+
                    |                       |
              Twelve Data              CoinGecko
              (XAU/USD 1h OHLC)        (BTC 4h OHLC)
                    |                       |
                    +-----------+-----------+
                                |
                    Level 1 trigger (signals.py)
                                |
              staleness gate -> event gate -> enrichment
                                |
                    +-----------+-----------+
                    |                       |
                 Ntfy push          Google Sheets journal
```

| File | Role |
|---|---|
| `main.py` | Flask routes, `check_asset()` orchestration, state, all gates |
| `signals.py` | Level 1 indicators + the two trigger functions |
| `data_fetch.py` | Twelve Data (gold) and CoinGecko (bitcoin) fetchers |
| `notify.py` | Ntfy push |
| `level2_analysis.py` | Support/resistance clustering, Bollinger Bands |
| `level3_analysis.py` | Candlestick patterns, Fibonacci retracements |
| `risk_analysis.py` | ATR, stop/target, position sizing |
| `event_filter.py` | FOMC/CPI/NFP window suppression |
| `macro_context.py` | DXY + rolling gold/DXY correlation |
| `seasonality.py` | 65yr monthly gold seasonality (gold only) |
| `journal_logger.py` | Appends signals to Google Sheets; shared `open_spreadsheet()` |
| `state_store.py` | Dedup state in the Sheet's `state` tab, `state.json` fallback |

---

## The trigger logic (read carefully before touching)

Both assets use `get_signals_recovery()` with `rsi_oversold=30,
rsi_overbought=70`. They are **identical in rule, different only in candle
interval**.

```
BUY  = RSI dipped below 30 within the last 6 candles
       AND RSI has now come back up to >= 30
       AND MACD line > MACD signal line

SELL = mirror (RSI above 70 within 6 candles, now back <= 70, MACD below signal)
```

Three things that look like bugs but are deliberate:

1. **It triggers on the recovery, not the extreme.** RSI sitting at 28 fires
   nothing. RSI climbing back through 30 with MACD confirming is the trigger.
   This is why alerts show RSI values like 36 or 55.

2. **EMA20/EMA50 is NOT part of the trigger.** It's display-only context. In
   a sustained trend the EMAs stay crossed for weeks, which would block every
   pullback-recovery setup the rule exists to catch.

3. **`get_signals()` (the old 50-midline rule) is still in `signals.py`** as
   the default parameter of `check_asset`, but nothing calls it. Kept for
   comparison. Don't delete without asking.

### Why not stricter

An earlier version required RSI to be below 30 **at the same instant** MACD
confirmed. Simulated over 30 days that produced **zero** signals — the two
conditions essentially never co-occur, because by the time MACD turns, RSI
has already recovered. The recovery pattern was the fix and is backed by
published strategy descriptions. Don't "tighten" this back without running
a simulation first.

---

## Gates, in execution order

`check_asset()` applies these before notifying. All record state so a
suppressed signal can never re-fire later as "new".

1. **Dedup** — `signal_id = "{time}_{type}"` vs `state[state_key]`.
2. **Staleness** — `MAX_SIGNAL_AGE_HOURS = 12`. Anything older is a
   re-discovery after a container restart, not an actionable setup.
   Recorded silently.
3. **Event window** — suppressed if inside a FOMC/CPI/NFP window. Set
   `SUPPRESS_IN_WINDOW = False` in `event_filter.py` to annotate instead.

Enrichment layers (ATR, seasonality, macro, Level 2, Level 3, journal) each
sit in their **own** try/except. **This is load-bearing.** One broken layer
must never block an alert. Preserve this pattern in anything you add.

---

## Routes

| Route | Purpose |
|---|---|
| `/` | Keep-alive. Must stay tiny — cron-job.org caps response size. |
| `/run` | Hourly check. Returns `"ok"` (2 bytes) deliberately. |
| `/backtest` | Replays history through the live rule. `?candles=` (max 5000). ~3s. |
| `/backfill` | Resolves open journal rows to stop/target/timeout. Idempotent. |
| `/stats` | Hit rate and expectancy, split by confluence and asset. |
| `/test-notify` | Ntfy smoke test. |

`/backtest` exists so the harness can run where pandas_ta and the API key
already live, instead of requiring a local install. It is the only route
returning a large response - never point cron-job.org at it.

`/backfill` should be scheduled daily once the journal is live. `/stats`
is read-only and safe to hit any time.

## Gotchas — the bug graveyard

Every one of these was a real production failure. Don't reintroduce them.

**`pandas_ta` numba JIT is a timeout hazard.** `ta.bbands()` triggers
numba/llvmlite compilation on first call in a process (~0.3s locally, far
worse on Render's shared CPU). This caused a real `WORKER TIMEOUT` +
`SIGKILL` crash. Bollinger Bands and ATR are therefore implemented in plain
pandas. **Do not "simplify" them back to pandas_ta.** `ta.ema/rsi/macd` are
fine and stay.

**Twelve Data defaults to America/New_York, not UTC.** Must pass
`"timezone": "UTC"` in params *and* `pd.to_datetime(..., utc=True)`. Getting
this wrong produced negative "hours ago" values in alerts.

**Timestamp tz-awareness differs by asset.** Gold and DXY come back
tz-aware UTC; always check `.tzinfo` before `tz_localize` vs `tz_convert`.
Calling `tz_localize` on an aware timestamp raises.

**CoinGecko `/ohlc` only accepts `days` in {1,7,14,30,90,180,365,max}.**
`days=4` returns `Invalid days parameter`. We use **30**, which yields 4h
candles (~180 of them). `/market_chart` returns no OHLC, so it can't be
used — Level 3 needs candle shape.

**Bitcoin therefore runs on 4h candles, not 1h.** Same rule, slower clock:
the 6-candle lookback spans 24h and signals fire roughly a third as often.
This is expected, not a bug.

**Render free tier has an ephemeral filesystem.** `state.json` is wiped by
deploys, Render's documented "may restart at any time" behaviour,
spin-down/up cycles, and OOM kills. This caused repeated duplicate alerts.
**Fixed:** state now lives in the `state` worksheet of the journal
spreadsheet (`state_store.py`), with `state.json` as a fail-soft fallback.
The staleness gate stays as a backstop for runs where Sheets is down.

**TA-Lib is not installable here.** `pandas_ta.cdl_pattern()` requires it.
All candlestick patterns in `level3_analysis.py` are hand-implemented.

**NFP is not always 12:30 UTC.** 08:30 US Eastern is 12:30 UTC under EDT
but 13:30 under EST. `event_filter.py` computes the offset from the DST
rule (second Sunday of March to first Sunday of November). The hardcoded
FOMC/CPI entries encode their own offsets, so check the season when adding
dates. Hand-rolled rather than `zoneinfo` because that needs `tzdata` on
Windows.

**gspread has no default timeout.** A hung Sheets call would run into
gunicorn's 120s and SIGKILL the run — the opposite of failing soft.
`journal_logger.open_spreadsheet()` sets 15s. Keep it.

**Render free tier blocks SMTP** (ports 25/465/587) — that's why Ntfy, not
email. Telegram is blocked in India. Don't propose either.

**Render's paid Cron Job product isn't free** — hence external cron-job.org
plus a keep-alive ping. A stale `render.yaml` from that era should not exist
in the repo; delete it if it reappears.

**cron-job.org's free tier caps response size** ("output too large"). Keep
`/` and `/run` responses tiny. `/run` returns `"ok"` (2 bytes) deliberately.

**cron-job.org's schedule UI silently drops multi-select values.** A missing
`:25` in the keep-alive schedule went unnoticed for hours. Verify the
crontab expression string after editing, don't trust the checkboxes.

---

## Deployment

**Render** — Web Service, free tier, auto-deploy on commit.

```
Build Command:  pip install -r requirements.txt
Start Command:  gunicorn main:app --timeout 120
```

The `--timeout 120` is **required**, not cosmetic — the default 30s killed
workers.

**cron-job.org** — two jobs:
| Job | URL | Schedule |
|---|---|---|
| Alert trigger | `/run` | `30 * * * *` (hourly) |
| Keep-alive | `/` | `5,15,25,35,45,55 * * * *` |

The keep-alive offsets avoid colliding with the hourly run and keep the
instance warm (Render spins down after 15 min idle; cold start ~1 min shows
a splash page that the cron reads as a failure).

### Environment variables

| Var | Required | Purpose |
|---|---|---|
| `TWELVE_DATA_API_KEY` | yes | Gold + DXY |
| `COINGECKO_API_KEY` | yes | Bitcoin (Demo plan, `x-cg-demo-api-key` header) |
| `NTFY_TOPIC` | yes | Push topic |
| `PYTHON_VERSION` | yes | `3.12.3` — 3.14 breaks pandas_ta |
| `GOOGLE_SHEETS_ID` | for journal | Sheet ID from its URL |
| `GOOGLE_SERVICE_ACCOUNT` | for journal | Full service-account JSON, one line |

**Never commit keys.** Two have already been leaked in chat and rotated.

---

## Rebuilding the GitHub repo

The repo was deleted. To recreate:

```bash
gh repo create gold-btc-alerts --public --source=. --push
# or: create empty repo on github.com, then
git init && git add . && git commit -m "Rebuild: full system"
git branch -M main
git remote add origin https://github.com/<user>/gold-btc-alerts.git
git push -u origin main
```

Then in Render: New Web Service → connect repo → set Build/Start commands
and env vars above. `.gitignore` already excludes `state.json`, `.env`, and
service-account JSON.

---

## Testing conventions

Every change in this project has been verified before deploy, and that
standard should hold:

- **Regression check**: the canonical fixture (`np.random.seed(123)`,
  30*16 hourly gold-like candles) must yield **exactly 7 signals** from
  `get_signals_recovery(rsi_oversold=30, rsi_overbought=70)`. If that number
  moves, the trigger logic changed — intentionally or not.
- **Edge cases**: insufficient candles, flat prices, and tz-aware vs naive
  timestamps have all caused real crashes. Test them.
- **End-to-end**: mock `main.notify_all` and call `check_asset()` with a
  synthetic dataframe rather than testing helpers in isolation. Several bugs
  only appeared at the integration seam.
- The sandbox blocks `freegoldapi.com`, so seasonality can only be verified
  in production. It does work there.

---

## Roadmap (priority order)

1. **Deploy the journal and measure expectancy.** Still the highest-value
   item, and the only one blocked on credentials. Needs `GOOGLE_SHEETS_ID`
   and `GOOGLE_SERVICE_ACCOUNT` on Render. Once live, schedule `/backfill`
   daily and read `/stats`. The question it answers: does the base rule
   have an edge, and does Level 2/3 confluence improve it or is it
   decoration?
2. **Hit `/backtest` on the deployed app.** Answers the same question
   immediately rather than waiting months for live signals. Runs on Render
   where the key and dependencies already exist; `backtest.py` is also
   runnable locally if you ever want the CSV.
3. **Decide on session gating from data.** `session_context.py` currently
   annotates only. Once backtest or journal data exists, split expectancy
   by liquidity bucket and gate thin sessions only if the data supports it.
4. **2027 CPI dates** — BLS had not published them as of 2026-09-13. Add
   when available. FOMC 2027 entries are tentative until confirmed at the
   preceding meeting.

### Done
- ~~Populate `KNOWN_EVENTS`~~ — FOMC through Sep 2027, CPI through Dec 2026.
- ~~Move state to Google Sheets~~ — `state_store.py`, with local fallback.
- ~~Outcome auto-fill~~ — `outcome_tracker.py` + `/backfill`.
- ~~Session awareness~~ — `session_context.py`.
- ~~Backtest harness~~ — `backtest.py`.

### Explicitly out of scope

- **Awesome Oscillator** — tested. 0 of 13 signals survived an AO-agreement
  filter; its 5/34 periods lag MACD's 12/26 so it's still negative at the
  recovery moment. Same failure mode as the old same-instant rule. Fine as
  display-only, useless as a gate.
- **Volume indicators** — no volume in either data feed.
- **Gold-INR / USD-INR** — built, then removed at the owner's request.
  `XAU/INR` is not a valid Twelve Data symbol; it must be computed as
  `XAU/USD × USD/INR`.
