"""
High-impact economic event filtering.

Gold's largest single-day moves cluster around scheduled US macro releases:
FOMC decisions, CPI, and Non-Farm Payrolls. A technical signal that fires
forty minutes before CPI is not a setup - it's a coin flip that happens to
look like a setup. This module suppresses (or flags) signals inside an
event window.

Design note: there is no reliable free economic-calendar API, so rather
than take a fragile dependency, this uses two mechanisms:

  1. NFP is computed algorithmically - it is released on the first Friday
     of each month at 08:30 US Eastern, a rule that does not change.
  2. FOMC and CPI dates are a hardcoded list, because they are published
     a year or more in advance by the Fed and BLS. UPDATE THIS LIST
     ANNUALLY - see KNOWN_EVENTS below. If the list is stale, the filter
     silently does less, it never breaks.

All times are stored and compared in UTC.
"""

import pandas as pd
from datetime import datetime, timezone, timedelta

# Hours before/after an event during which signals are considered
# contaminated by event risk.
WINDOW_BEFORE_HOURS = 4
WINDOW_AFTER_HOURS = 2

# Whether to fully suppress signals in an event window, or just annotate
# them. Suppressing is the safer default; set False to only flag.
SUPPRESS_IN_WINDOW = True

# ---------------------------------------------------------------------
# UPDATE ANNUALLY. Datetimes are UTC.
# FOMC statement releases are 18:00 UTC (14:00 ET) on the second day of
# each two-day meeting. CPI releases are 12:30 UTC (08:30 ET).
# Sources: federalreserve.gov/monetarypolicy/fomccalendars.htm
#          bls.gov/schedule/news_release/cpi.htm
# ---------------------------------------------------------------------
KNOWN_EVENTS = [
    # ("2026-01-28 19:00", "FOMC"),
    # ("2026-01-13 13:30", "CPI"),
]


def _first_friday(year: int, month: int) -> datetime:
    """First Friday of a given month - the NFP release day."""
    d = datetime(year, month, 1, tzinfo=timezone.utc)
    while d.weekday() != 4:  # 4 = Friday
        d += timedelta(days=1)
    return d


def _nfp_datetimes(around: datetime) -> list:
    """
    NFP release datetimes for the month of `around` and its neighbours,
    at 12:30 UTC (08:30 ET). Covers month boundaries.
    """
    out = []
    for offset in (-1, 0, 1):
        month = around.month + offset
        year = around.year
        if month < 1:
            month, year = 12, year - 1
        elif month > 12:
            month, year = 1, year + 1
        friday = _first_friday(year, month)
        out.append(friday.replace(hour=12, minute=30))
    return out


def get_active_event(now: datetime = None) -> str:
    """
    Returns the name of a high-impact event whose window currently contains
    `now`, or "" if none. Window is WINDOW_BEFORE_HOURS before through
    WINDOW_AFTER_HOURS after the release.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    candidates = [(dt, "NFP") for dt in _nfp_datetimes(now)]
    for raw, name in KNOWN_EVENTS:
        try:
            dt = pd.Timestamp(raw, tz="UTC").to_pydatetime()
            candidates.append((dt, name))
        except (ValueError, TypeError):
            continue  # a malformed entry must never break the run

    for event_time, name in candidates:
        start = event_time - timedelta(hours=WINDOW_BEFORE_HOURS)
        end = event_time + timedelta(hours=WINDOW_AFTER_HOURS)
        if start <= now <= end:
            hours_to = (event_time - now).total_seconds() / 3600
            when = f"in {hours_to:.1f}h" if hours_to > 0 else f"{abs(hours_to):.1f}h ago"
            return f"{name} {when}"
    return ""


def describe_event_risk(active_event: str) -> str:
    """Notification-ready line for a signal inside an event window."""
    if not active_event:
        return ""
    return (
        f"Event risk: {active_event}. Gold's largest single-day moves cluster "
        f"around these releases - treat any technical setup here with caution."
    )
