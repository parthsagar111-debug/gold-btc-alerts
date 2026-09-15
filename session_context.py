"""
Trading session awareness.

Gold trades nearly 24 hours, but liquidity is not evenly spread. A setup
that forms at 03:00 UTC in thin Asian hours is not the same quality as one
forming during the London/New York overlap, even when the indicators look
identical. Every candle timestamp already carries this information; nothing
used it until now.

Deliberately ANNOTATES rather than gates. The honest position is that we do
not yet have evidence that Asian-session signals perform worse for this
specific strategy - we only have the general market structure argument. So
the session is recorded on every signal and written to the journal, and
backtest.py can split expectancy by session. Once there is data, gating
becomes an evidence-based decision instead of a guess.

All boundaries are UTC.
"""

# Suppress signals that fire in thin-liquidity sessions. Set False to
# annotate only (the pre-backtest behaviour).
SUPPRESS_THIN_SESSIONS = True

SESSIONS = [
    (0, 6, "Asian", "thin"),
    (7, 11, "London morning", "good"),
    (12, 16, "London/NY overlap", "deepest"),
    (17, 20, "NY afternoon", "good"),
    (21, 23, "Late NY / rollover", "thin"),
]


def classify_session(timestamp) -> dict:
    """
    Returns {"session": str, "liquidity": str, "hour_utc": int} for a
    pandas Timestamp or datetime. Falls back to the late/rollover bucket
    for any hour not explicitly covered.
    """
    hour = int(timestamp.hour)
    for start, end, name, liquidity in SESSIONS:
        if start <= hour <= end:
            return {"session": name, "liquidity": liquidity, "hour_utc": hour}
    return {"session": "Late NY / rollover", "liquidity": "thin", "hour_utc": hour}


def describe_session(timestamp) -> str:
    """Notification-ready line. Only warns when liquidity is thin."""
    info = classify_session(timestamp)
    if info["liquidity"] == "thin":
        return (
            f"Session: {info['session']} ({info['hour_utc']:02d}:00 UTC) - thin liquidity, "
            f"so this setup is lower quality than the same setup in London/NY hours."
        )
    return f"Session: {info['session']} ({info['hour_utc']:02d}:00 UTC), {info['liquidity']} liquidity."
