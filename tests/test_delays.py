# tests/test_delays.py
import time, pytest
from hydra_reposter.utils.delays import human_delay, async_sleep_human


def test_human_delay_range():
    for _ in range(100):
        d = human_delay(0.6, 2.2)
        assert 0.6 <= d <= 2.2


@pytest.mark.asyncio
async def test_async_sleep_human():
    start = time.monotonic()
    await async_sleep_human(0.1, 0.2)
    elapsed = time.monotonic() - start
    assert 0.1 <= elapsed <= 0.25