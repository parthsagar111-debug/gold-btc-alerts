"""
Regression check for the Level 1 trigger - see CLAUDE.md "Testing conventions".

The canonical fixture used to be described only in prose ("seed 123, 30*16
hourly candles"), which turned out to be ambiguous: the original "7" could
not be reproduced. This file pins the exact generator so the number means
something. If the count moves, the trigger logic changed.

Run:  python tests/test_regression.py     (or: pytest tests/)
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from signals import add_indicators, get_signals_recovery  # noqa: E402

EXPECTED_SIGNALS = 6
EXPECTED_BY_TYPE = {"BUY": 4, "SELL": 2}


def canonical_fixture() -> pd.DataFrame:
    """30 days x 16 hourly gold-like candles, additive random walk from 2000."""
    n = 30 * 16
    np.random.seed(123)
    close = 2000 + np.cumsum(np.random.randn(n) * 3)
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame(
        {"Open": close, "High": close + 1, "Low": close - 1, "Close": close},
        index=idx,
    )


def test_canonical_fixture_signal_count():
    signals = get_signals_recovery(
        add_indicators(canonical_fixture()), rsi_oversold=30, rsi_overbought=70
    )
    assert len(signals) == EXPECTED_SIGNALS, f"got {len(signals)}, expected {EXPECTED_SIGNALS}"
    assert signals["type"].value_counts().to_dict() == EXPECTED_BY_TYPE


if __name__ == "__main__":
    test_canonical_fixture_signal_count()
    print(f"OK - canonical fixture yields {EXPECTED_SIGNALS} signals {EXPECTED_BY_TYPE}")
