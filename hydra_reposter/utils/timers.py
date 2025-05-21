"""
hydra_reposter.utils.timers
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Асинхронные задержки и вспомогательные таймеры.

* ``async_backoff`` — экспоненциальный бэкофф с джиттером
  (используем внутри retry-циклов).
* ``sleep_human`` — короткая «человеческая» пауза 0.7‑1.8 с для
  имитации живого поведения при пересылке сообщений.
"""

from __future__ import annotations

import asyncio
import random
from typing import Awaitable, Callable


async def async_backoff(
    attempt: int,
    base: float = 1.0,
    factor: float = 2.0,
    max_delay: float = 60.0,
) -> None:
    """
    Асинхронная задержка **exp(base * factor^attempt + jitter)**.

    :param attempt: номер попытки (0, 1, 2…)
    :param base: базовая задержка в секундах
    :param factor: коэффициент экспоненты
    :param max_delay: верхний предел задержки
    """
    delay = min(base * (factor**attempt), max_delay)
    jitter = random.uniform(0, delay * 0.1)  # ±10 %
    await asyncio.sleep(delay + jitter)


async def sleep_human(
    min_sec: float = 0.7,
    max_sec: float = 1.8,
    after: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """
    Короткая «человеческая» задержка.

    :param min_sec: минимальное время ожидания
    :param max_sec: максимальное время ожидания
    :param after: опциональная корутина, которую нужно вызвать после sleep
    """
    await asyncio.sleep(random.uniform(min_sec, max_sec))
    if after:
        await after()
