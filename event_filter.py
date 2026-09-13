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
from datetime import date, datetime, timezone, timedelta

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
    # UTC offset follows US daylight saving: 18:00 / 12:30 UTC while EDT
    # applies, 19:00 / 13:30 UTC under EST (2026: EDT Mar 8 - Nov 1;
    # 2027: EDT Mar 14 - Nov 7).
    # Populated 2026-09-13. BLS had not yet published its 2027 schedule,
    # so CPI entries stop at Dec 2026 - add 2027 CPI once bls.gov lists it.
    # FOMC 2027 dates are tentative until confirmed at the preceding meeting.

    # FOMC statement days (second day of each meeting)
    ("2026-09-16 18:00", "FOMC"),
    ("2026-10-28 18:00", "FOMC"),
    ("2026-12-09 19:00", "FOMC"),
    ("2027-01-27 19:00", "FOMC"),
    ("2027-03-17 18:00", "FOMC"),
    ("2027-04-28 18:00", "FOMC"),
    ("2027-06-09 18:00", "FOMC"),
    ("2027-07-28 18:00", "FOMC"),
    ("2027-09-15 18:00", "FOMC"),

    # CPI releases (reference month in comment)
    ("2026-10-14 12:30", "CPI"),  # Sep 2026
    ("2026-11-10 13:30", "CPI"),  # Oct 2026
    ("2026-12-10 13:30", "CPI"),  # Nov 2026
]


def _first_friday(year: int, month: int) -> datetime:
    """First Friday of a given month - the NFP release day."""
    d = datetime(year, month, 1, tzinfo=timezone.utc)
    while d.weekday() != 4:  # 4 = Friday
        d += timedelta(days=1)
    return d


def _nth_sunday(year: int, month: int, n: int) -> date:
    """The n-th Sunday of a given month."""
    d = date(year, month, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)  # 6 = Sunday
    return d + timedelta(weeks=n - 1)


def _us_eastern_utc_offset_hours(day: date) -> int:
    """
    UTC offset of US Eastern time on `day`, for releases at 08:30 local.

    US DST (since 2007) runs from the second Sunday of March to the first
    Sunday of November, switching at 02:00 local - so by 08:30 on either
    transition day the new offset already applies, and a date comparison
    is exact. Hand-rolled rather than zoneinfo because zoneinfo needs the
    `tzdata` package on Windows.
    """
    dst_start = _nth_sunday(day.year, 3, 2)
    dst_end = _nth_sunday(day.year, 11, 1)
    return -4 if dst_start <= day < dst_end else -5


def _nfp_datetimes(around: datetime) -> list:
    """
    NFP release datetimes for the month of `around` and its neighbours,
    at 08:30 US Eastern converted to UTC (12:30 UTC under EDT, 13:30 UTC
    under EST). Covers month boundaries.
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
        utc_hour = 8 - _us_eastern_utc_offset_hours(friday.date())
        out.append(friday.replace(hour=utc_hour, minute=30))
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
