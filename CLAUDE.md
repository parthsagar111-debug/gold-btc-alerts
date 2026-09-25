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

## Backtest findings (2026-09-15)

Run on **852 trades, 10 years of real hourly XAU/USD (2012-2022)**, sourced
from `ejtraderLabs/historical-data`. Read this before changing parameters.

**The original configuration had no edge.** 1.5 x ATR stop / 2R target,
all sessions: **-0.040R** expectancy, 33.3% win rate. Breakeven for 2R:1R
is exactly 33.3%, so it sat precisely on the coin-flip line - and that is
before spread. Ten years and 852 trades is a properly powered null result,
not a small-sample fluke.

**Level 2 and Level 3 do not discriminate.** The confluence flag was true
on **99.4%** of trades (847/852). A flag that is almost always true carries
no information, so those layers have never filtered anything. They remain
display-only and are *unvalidated* - do not describe them as improving
signal quality. `backtest.py` now emits a graded `confluence_score` instead
of the useless boolean, so future runs can actually test them.

**Thin sessions are the one significant finding.** -0.144R, t = -1.98 -
the only result in the whole run that cleared significance. Hence
`SUPPRESS_THIN_SESSIONS = True`. Note the asymmetry: "thin hours lose" is
significant; "good hours win" is NOT (t = 0.85, CI spans zero).

**Gold is BUY-only.** The single largest finding. Over the same 531
trades, split by direction:

| | expectancy | t | win | in / out |
|---|---|---|---|---|
| BUY only | **+0.260R** | **+2.74** | 45.7% | +0.229 / +0.299 |
| SELL only | -0.011R | -0.14 | 37.8% | -0.045 / +0.022 |
| Both (previous) | +0.113R | +1.83 | 41.4% | +0.089 / +0.139 |

SELL signals were contributing nothing while halving overall expectancy.
Dropping them is the first change in this project to clear statistical
significance (t > 1.96).

Robustness, because a result this good deserves suspicion:
- **10 of 11 years positive.**
- **Works in both gold regimes**, which was the main worry - a mean-reversion
  long-only rule could easily be a bull-market artifact. 2012-2015 was a
  gold *bear* market (1790 -> 1050) and BUY-only returned **+0.335R
  (t = 2.11)** through it; the 2019-2022 bull returned **+0.382R (t = 2.18)**.
  Both individually significant, in opposite regimes.
- **Parameter plateau, not a spike** - every stop/target cell from 1.5 to
  3.0 x ATR and 1.5R to 4R is positive, improving monotonically.
- **Holding period insensitive** - stable from 2 to 7 days.

Mechanically this is what you would expect: buying oversold dips is a
mean-reversion trade, and shorting overbought in an instrument with a
persistent structural bid fights the tape.

Note the expectancy gradient continues past the current settings (3.0 ATR /
4R scored +0.336R). That was NOT adopted - it is untested out-of-sample,
and chasing a monotonic gradient is how parameter sets end up absurd.

**Bitcoin is untested.** It keeps both directions because no equivalent
backtest exists for it. Do not assume the gold result transfers - different
asset, different regime, 4h candles.

**Current configuration** - RSI 30/70, stop 2.5 x ATR, target 3R, thin
sessions dropped, gold BUY-only:

| | expectancy | n |
|---|---|---|
| Full 10yr | **+0.113R** (t = 1.83, 41.4% win) | 531 |
| In-sample (2012 - Jun 2017) | +0.089R | 276 |
| Out-of-sample (Jun 2017 - 2022) | **+0.139R** | 255 |
| Positive years | 9 / 11 | |

Chosen over higher in-sample scorers deliberately. RSI 25/75 variants
peaked at +0.272R in-sample but collapsed to +0.070R out-of-sample on
n=105 - textbook overfitting. This config *improves* out-of-sample and sits
on a broad plateau: every stop >= 2.0 x ATR is positive across all target
ratios, improving monotonically as the stop widens. That matches a
mechanical explanation (a tight stop was being knocked out by noise before
moves developed) rather than a curve-fit spike.

**Honest caveats.** The dataset ends March 2022, so it excludes the
central-bank-driven regime that took gold past $4,000 - behaviour there is
untested.

On costs: an earlier note claimed ~0.05R per trade. That was right for the
backtest era and is now too pessimistic. Spread cost scales inversely with
price, and gold tripled while spreads stayed flat in dollar terms. At the
sample's ~$1,380 average a 0.40 spread with slippage cost ~0.079R (30% of
the edge); at ~$4,400 it costs ~0.012R (under 5%). `risk_analysis.py`
reports this per signal.

**Comparison against the published `analyze-gold` skill (mcpmarket)**,
tested on our data rather than read off the page:
- Its session window (08:00-21:00 UTC) scores +0.259R vs our +0.260R -
  independent convergence on the same answer.
- Its 1 x ATR stop floor scores +0.138R vs our 2.5 x ATR at +0.260R. Its own
  text says "gold wicks hunt tight stops", then sets the floor too tight.
- Its "skip when H1 ATR > 20" rule is not supported by our data: the highest
  volatility quartile was our *best* in-sample bucket (+0.542R, t = 3.38).
  That does **not** mean high vol is good - the effect failed out-of-sample,
  see "High-volatility finding" below. The defensible claim is only that
  there is no evidence for *skipping* high vol. Its absolute thresholds are also stale - its worked
  example prices gold at 2345, so 20 pts was 0.85% of price then and 0.44%
  now, meaning the rule would fire near-constantly today. ATR *multipliers*
  are regime-proof; absolute point thresholds are not.
- Event-gate width is immaterial: only 5 of 243 signals fall inside our
  4h/2h NFP window, and suppressing them moves expectancy by 0.001R.

## High-volatility finding: does NOT survive (2026-09-25)

Roadmap item 3. Tested the same way as BUY-only: same 243 trades (BUY-only,
thin dropped, 2.5 x ATR / 3R, 48-candle hold), same Jun-2017 split. The
original numbers were reproduced exactly first. Two details matter. "Volatility"
here means **ATR as % of price**, not absolute ATR. The quartile cutoff was
computed on the **full sample**, which is lookahead: a live rule could not
have known it in 2013.

**Verdict: do not prefer, weight or gate on high volatility.** It was an
in-sample artifact of two regimes, not a property of the setup.

Even the original result was weaker than it looked. +0.542R vs +0.165R is a
difference test of t = 1.90, so it was never significant *as a difference*.
t = 3.38 only shows the bucket beats zero, which the base rule already does.
The buckets are not monotonic either (Q1 +0.315, Q2 +0.004, Q3 +0.177, Q4
+0.542).

| Test | high-vol | rest | verdict |
|---|---|---|---|
| In-sample (cutoff 0.344% ATR, set in-sample) | +0.616R (n=34) | +0.098R | edge |
| **Out-of-sample, same cutoff** | **+0.296R (n=20)** | **+0.300R** | **none (diff t = -0.01)** |
| OOS, quartile recomputed within the half | +0.111R | +0.362R | reversed |

- **Year-by-year: it is two regimes.** 36 of the 61 high-vol trades fall in
  2013-2016, the gold crash, where high vol beat the rest in every year.
  After that it is 2019 -1.00R (n=2), 2020 +0.456R vs +0.262R, and 2021
  -0.028R vs +0.523R. 2017 and 2022 have no high-vol trades at all. So a fixed
  ATR% level is mostly a proxy for "2013 or 2020".
- **Parameter neighbourhood: no plateau, just a sign flip.** In-sample
  high-vol wins in every variant. Out-of-sample it wins in almost none:
  - stop x target grid (1.5-3.0 x ATR, 1.5-4R): high-vol minus rest is
    <= 0 OOS in **16 of 16** cells (range -0.37 to -0.00).
  - ATR period 7/14/21/28: worse OOS in **4 of 4**.
  - cutoff top 50/33/25/20/10%: worse OOS in 4 of 5, and top 20% is only
    +0.035R ahead on n=19.
  - Absolute ATR instead of ATR%: +0.104R vs +0.374R OOS.
- **Hold-period dependent.** 66% of high-vol trades exit on the 48-candle
  timeout rather than stop or target, because wide ATR brackets are rarely
  reached in 2 days. The edge is mostly mark-to-market drift. With a 24h
  hold, OOS high-vol is -0.005R vs +0.270R.
- **No mechanism.** SELL signals gain nothing from high vol out-of-sample
  (+0.011R vs +0.024R).

**The one variant that keeps its sign, and why it still isn't adopted.**
Ranking ATR% against its own *trailing* N hours has no lookahead and is
regime-relative, so it measures a vol spike rather than a vol level. That
version stays ahead OOS for every window (N = 500/1000/2000/5000h, +0.06 to
+0.19R). But the OOS difference t-stats are 0.18-0.64, and it beats the rest
in only 5-7 of 11 years. Only N=2000h clears t = 1.96 on the full sample
(t = 2.38), and picking one window out of four is the cherry-pick this file
warns about. At most this is something to *annotate* in the journal and
revisit on live data. It is not a gate.

Harness: the test reused the live `get_signals_recovery` and plain-pandas
`add_atr`, run on `ejtraderLabs/historical-data` `XAUUSD/XAUUSDh1.csv`
(prices are x100 in that file). It was a one-off script and was not
committed; the numbers above are enough to avoid re-running it.

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

**`updated_at_utc` in the Sheets `state` tab is last-CHANGED, not
last-run.** `save_state` only stamps a new timestamp when the value
actually differs, so a stale timestamp is the normal state of a quiet
market, NOT evidence the app has stopped. This already caused one false
alarm. To tell "running but quiet" from "dead", use cron-job.org's run
history (or add an unconditionally-stamped `last_run_utc` key).

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

- **Regression check**: `python tests/test_regression.py`. The canonical
  fixture (pinned in that file: `np.random.seed(123)`, 30*16 hourly
  candles, `2000 + cumsum(randn * 3)`) must yield **exactly 6 signals
  (4 BUY / 2 SELL)** from
  `get_signals_recovery(rsi_oversold=30, rsi_overbought=70)`. If that number
  moves, the trigger logic changed — intentionally or not.
  An older prose-only version of this note said "7". That fixture was never
  recorded and couldn't be reproduced. The pinned one gives 6 at both the
  rebuild commit `f2bc68b` and at `10b72b4`, and the count doesn't change
  with start price, scale, tz, or additive vs geometric walks. So the
  trigger didn't drift. The baseline was re-pinned at 6 on 2026-09-25.
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
3. **Backtest Bitcoin.** It currently runs both directions on untested
   settings inherited from gold. Needs its own 4h-candle history.
4. **Re-test on post-2022 data.** The current backtest ends March 2022 and
   misses the 2022+ central-bank regime. Sourcing hourly data for that
   period would test whether the edge survives it.
5. **2027 CPI dates** — BLS had not published them as of 2026-09-13. Add
   when available. FOMC 2027 entries are tentative until confirmed at the
   preceding meeting.

### Done
- ~~Populate `KNOWN_EVENTS`~~ — FOMC through Sep 2027, CPI through Dec 2026.
- ~~Move state to Google Sheets~~ — `state_store.py`, with local fallback.
- ~~Outcome auto-fill~~ — `outcome_tracker.py` + `/backfill`.
- ~~Session awareness~~ — `session_context.py`.
- ~~Backtest harness~~ — `backtest.py`.
- ~~Session gating~~ — evidence-based, see Backtest findings.
- ~~Stop/target tuning~~ — 2.5 x ATR / 3R, validated out-of-sample.
- ~~Direction filter~~ — gold BUY-only, significant in both regimes.

### Explicitly out of scope

- **Awesome Oscillator** — tested. 0 of 13 signals survived an AO-agreement
  filter; its 5/34 periods lag MACD's 12/26 so it's still negative at the
  recovery moment. Same failure mode as the old same-instant rule. Fine as
  display-only, useless as a gate.
- **Preferring high-volatility setups** — tested 2026-09-25, failed
  out-of-sample (+0.296R vs +0.300R). See "High-volatility finding". Don't
  chase it again without new post-2022 data.
- **Volume indicators** — no volume in either data feed.
- **Gold-INR / USD-INR** — built, then removed at the owner's request.
  `XAU/INR` is not a valid Twelve Data symbol; it must be computed as
  `XAU/USD × USD/INR`.
