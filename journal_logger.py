"""
Signal journal: append every fired signal to a Google Sheet.

This is the most important module in the project and the least exciting.
Levels 1, 2 and 3 all rest on an unmeasured assumption - that the base
rule has an edge. Without a journal there is no hit rate, no expectancy,
and no way to know whether confluence layers improve outcomes or merely
make notifications look more authoritative. With thirty-odd logged
signals you can answer that empirically.

Columns are written so outcomes can be filled in later (manually or by a
follow-up job) and expectancy computed:
    expectancy = (win_rate x avg_win_R) - (loss_rate x avg_loss_R)

SETUP (one time):
  1. Google Cloud Console -> create project -> enable Google Sheets API
  2. Create a Service Account -> create a JSON key -> download it
  3. Create a Google Sheet, note its ID from the URL
  4. Share that Sheet with the service account's client_email (Editor)
  5. Set two env vars on Render:
       GOOGLE_SHEETS_ID         = the sheet ID
       GOOGLE_SERVICE_ACCOUNT   = the FULL JSON key, pasted as one line

Fails soft by design: if credentials are missing or Sheets is down, the
caller logs the error and the alert still sends.
"""

import os
import json
from datetime import datetime, timezone

GOOGLE_SHEETS_ID = os.environ.get("GOOGLE_SHEETS_ID", "")
GOOGLE_SERVICE_ACCOUNT = os.environ.get("GOOGLE_SERVICE_ACCOUNT", "")

HEADER_ROW = [
    "logged_at_utc", "asset", "signal_type", "signal_time_utc",
    "signal_price", "price_now", "hours_old",
    "rsi", "ema20", "ema50", "macd_state",
    "atr", "stop", "target", "risk_per_unit",
    "level2_context", "level3_context", "seasonality", "macro", "event_risk",
    "outcome", "exit_price", "r_multiple", "notes",
    # Appended last so rows written before it existed stay aligned.
    # SIGNAL = validated RSI 30 rule; WATCH = looser RSI 45 tier (main.py).
    "tier",
]


# Per-request timeout for Sheets API calls. gspread has none by default, and
# a hung request would run into gunicorn's 120s worker timeout and SIGKILL
# the whole run - the opposite of failing soft.
SHEETS_TIMEOUT_SECONDS = 15


def open_spreadsheet():
    """
    Authorised gspread Spreadsheet for GOOGLE_SHEETS_ID. Shared by the
    journal (first worksheet) and state_store.py (the "state" worksheet).
    """
    import gspread
    from google.oauth2.service_account import Credentials

    if not GOOGLE_SHEETS_ID or not GOOGLE_SERVICE_ACCOUNT:
        raise RuntimeError(
            "GOOGLE_SHEETS_ID / GOOGLE_SERVICE_ACCOUNT not set - see setup "
            "instructions at the top of journal_logger.py"
        )

    creds = Credentials.from_service_account_info(
        json.loads(GOOGLE_SERVICE_ACCOUNT),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    client = gspread.authorize(creds)
    client.http_client.set_timeout(SHEETS_TIMEOUT_SECONDS)
    return client.open_by_key(GOOGLE_SHEETS_ID)


def _get_worksheet():
    """Opens the first worksheet, creating the header row if the sheet is empty."""
    sheet = open_spreadsheet().sheet1

    if not sheet.get_all_values():
        sheet.append_row(HEADER_ROW)
    return sheet


def log_signal_to_journal(**fields) -> None:
    """
    Appends one signal row. Accepts any subset of HEADER_ROW as keyword
    arguments; anything not supplied is left blank so outcome columns can
    be filled in later.
    """
    sheet = _get_worksheet()
    fields.setdefault("logged_at_utc", datetime.now(timezone.utc).isoformat())
    sheet.append_row([str(fields.get(col, "")) for col in HEADER_ROW])
