import time
import pytest
from pathlib import Path

from hydra_reposter.utils.quarantine import add_quarantine, is_quarantined

@pytest.fixture(autouse=True)
def fake_time(monkeypatch):
    now = [1_000_000]
    monkeypatch.setattr(time, "time", lambda: now[0])
    return now

def test_add_and_expire(tmp_path: Path, fake_time):
    session = tmp_path / "fake.session"
    add_quarantine(session, reason="PeerFlood", ttl=3600)
    assert is_quarantined(session)            # ещё активно
    fake_time[0] += 3601                      # время вперёд + 1 секунда
    assert not is_quarantined(session)        # карантин истёк