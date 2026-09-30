"""
State round-trip through state_store - the seam an in-memory end-to-end test
misses. Every key main.py dedups on must survive save -> load, or that alert
re-fires every run. Sheets is unavailable here, so this exercises the
state.json fallback, which applies the same STATE_KEYS whitelist.

Run:  python tests/test_state_store.py     (or: pytest tests/)
"""

import os
import re
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import state_store  # noqa: E402


def _keys_main_uses() -> set:
    """Every state key main.py reads or writes, found by scanning the source."""
    with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
        source = f.read()
    return set(re.findall(r'"((?:gold|btc)_last_\w+|last_status_date)"', source))


def test_every_main_key_is_persisted():
    missing = _keys_main_uses() - set(state_store.STATE_KEYS)
    assert not missing, f"state keys used in main.py but dropped on load: {missing}"


def test_round_trip_via_local_fallback():
    state = {key: f"2026-10-01 00:00:00+00:00_{key}" for key in state_store.STATE_KEYS}
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            state_store.save_state(state)
            loaded = state_store.load_state()
        finally:
            os.chdir(cwd)
    assert loaded == state, f"lost on round trip: {set(state.items()) - set(loaded.items())}"


if __name__ == "__main__":
    test_every_main_key_is_persisted()
    test_round_trip_via_local_fallback()
    print(f"OK - {len(state_store.STATE_KEYS)} state keys persist: {state_store.STATE_KEYS}")
