"""
Cross-asset signal correlation for Gold-INR notifications.

Gold-INR = Gold-USD price x USD/INR exchange rate (roughly). When a
Gold-INR signal fires, this checks whether Gold-USD and/or USD/INR also
signaled recently, so the notification can explain WHETHER the INR move
is driven by gold itself, the currency, both, or neither (the last case
being the most interesting - it suggests an India-specific effect, like
festival demand or import duty news, rather than a global gold/currency move).

State (recent signal timestamps) is read from the same state dict that
main.py already maintains - no new storage needed.
"""

from datetime import datetime, timezone


LOOKBACK_HOURS = 3  # how far back to consider a "recent" signal as related


def _hours_since(timestamp_str: str) -> float:
    """Returns hours elapsed since an ISO timestamp string, or None if invalid/missing."""
    if not timestamp_str:
        return None
    try:
        # state stores signal_id as "{time}_{type}" - extract just the time part
        time_part = timestamp_str.rsplit("_", 1)[0]
        signal_time = datetime.fromisoformat(time_part)
        if signal_time.tzinfo is None:
            signal_time = signal_time.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - signal_time).total_seconds() / 3600
    except (ValueError, IndexError):
        return None


def get_gold_inr_context(state: dict) -> str:
    """
    Builds a short context string for a Gold-INR notification, based on
    whether Gold-USD and/or USD/INR signals are recent (within LOOKBACK_HOURS).

    Expects state to contain 'gold_last_signal' and 'usdinr_last_signal' keys
    (signal_id strings in the format "{time}_{type}"), same as how main.py
    already tracks gold_last_signal and btc_last_signal.
    """
    gold_signal_id = state.get("gold_last_signal", "")
    usdinr_signal_id = state.get("usdinr_last_signal", "")

    gold_hours_ago = _hours_since(gold_signal_id)
    usdinr_hours_ago = _hours_since(usdinr_signal_id)

    gold_recent = gold_hours_ago is not None and gold_hours_ago <= LOOKBACK_HOURS
    usdinr_recent = usdinr_hours_ago is not None and usdinr_hours_ago <= LOOKBACK_HOURS

    if gold_recent and usdinr_recent:
        gold_type = gold_signal_id.rsplit("_", 1)[-1]
        usdinr_type = usdinr_signal_id.rsplit("_", 1)[-1]
        rupee_direction = "weakening" if usdinr_type == "BUY" else "strengthening"
        return (
            f"Context: GOLD-USD also signaled {gold_type} ({gold_hours_ago:.1f}h ago) "
            f"and the Rupee is {rupee_direction} ({usdinr_hours_ago:.1f}h ago) - "
            f"both effects are reinforcing this Gold-INR move."
        )
    elif gold_recent:
        gold_type = gold_signal_id.rsplit("_", 1)[-1]
        return f"Context: GOLD-USD also signaled {gold_type} ({gold_hours_ago:.1f}h ago) - gold itself is driving this move."
    elif usdinr_recent:
        usdinr_type = usdinr_signal_id.rsplit("_", 1)[-1]
        rupee_direction = "weakening" if usdinr_type == "BUY" else "strengthening"
        return f"Context: the Rupee is {rupee_direction} ({usdinr_hours_ago:.1f}h ago) - the currency move is driving this, not gold itself."
    else:
        return (
            "Context: no matching Gold-USD or Rupee signal recently - this looks "
            "Gold-INR-specific (check for India demand news, import duty changes, "
            "or festival/wedding season effects)."
        )
