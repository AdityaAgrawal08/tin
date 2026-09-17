from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _settled_switchboard_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """A test process is always young; only tests about restarts pretend Tin just came up."""
    from tin_lite import activities

    monkeypatch.setattr(activities, "process_uptime_seconds", lambda: 3600.0)
