"""
Run state persistence: Google Sheet first, local state.json as fallback.

Render's free tier has an ephemeral filesystem, so a state.json-only store
was wiped by deploys, restarts, spin-down cycles and OOM kills - and every
wipe let the next run re-alert an old signal as "new". State now lives in a
"state" worksheet of the journal's spreadsheet (same credentials), which
survives all of that. The staleness gate in main.py stays as a backstop.

Worksheet layout (created automatically on first use):
    key | value | updated_at_utc

Fails soft in both directions, and neither function ever raises:
  - load: if Sheets is unreachable, read state.json; if that is missing or
    unreadable too, start from empty state.
  - save: always write state.json, then try Sheets. A key that is None in
    this run's state never blanks out a value already in the Sheet, so a run
    that fell back to an empty local file can't erase good dedup state.
"""

import os
import json
from datetime import datetime, timezone

STATE_FILE = "state.json"
STATE_WORKSHEET = "state"
STATE_HEADER = ["key", "value", "updated_at_utc"]
STATE_KEYS = ("gold_last_signal", "btc_last_signal", "last_status_date")


def _empty_state() -> dict:
    return {key: None for key in STATE_KEYS}


def _state_worksheet():
    """The "state" worksheet, created with a header row if it doesn't exist."""
    import gspread
    from journal_logger import open_spreadsheet

    book = open_spreadsheet()
    try:
        return book.worksheet(STATE_WORKSHEET)
    except gspread.WorksheetNotFound:
        sheet = book.add_worksheet(title=STATE_WORKSHEET, rows=20, cols=len(STATE_HEADER))
        sheet.update(values=[STATE_HEADER], range_name="A1")
        return sheet


def _load_local() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r") as f:
        return json.load(f)


def load_state() -> dict:
    state = _empty_state()

    # Local file first, so any value Sheets doesn't have can still fill in.
    try:
        state.update({k: v for k, v in _load_local().items() if k in STATE_KEYS and v})
    except Exception as local_error:
        print(f"[state] {STATE_FILE} unreadable (ignoring it): {local_error}")

    try:
        rows = _state_worksheet().get_all_values()
        for row in rows[1:]:
            if len(row) >= 2 and row[0] in STATE_KEYS and row[1]:
                state[row[0]] = row[1]
        print("[state] Loaded from Google Sheets.")
    except Exception as sheets_error:
        print(f"[state] Sheets unavailable, using {STATE_FILE} fallback: {sheets_error}")

    return state


def save_state(state: dict) -> None:
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, default=str)
    except Exception as local_error:
        print(f"[state] Could not write {STATE_FILE}: {local_error}")

    try:
        sheet = _state_worksheet()
        existing = {row[0]: row for row in sheet.get_all_values()[1:] if row and row[0]}
        now = datetime.now(timezone.utc).isoformat()

        rows = [STATE_HEADER]
        for key in STATE_KEYS:
            prev = (existing.get(key, []) + ["", "", ""])[:3]
            value = state.get(key)
            if value is None or str(value) == prev[1]:
                rows.append([key, prev[1], prev[2]])
            else:
                rows.append([key, str(value), now])

        sheet.update(values=rows, range_name="A1")
        print("[state] Saved to Google Sheets.")
    except Exception as sheets_error:
        print(f"[state] Sheets save failed (kept {STATE_FILE} only): {sheets_error}")
