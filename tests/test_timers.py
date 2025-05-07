import time
import pytest

from hydra_reposter.utils.timers import async_backoff

@pytest.mark.asyncio
async def test_backoff_grows():
    start = time.monotonic()
    await async_backoff(2, base=0.1)
    assert time.monotonic() - start >= 0.2