"""
hydra_reposter.utils.delays
~~~~~~~~~~~~~~~~~~~~~~~~~~~

«Человеческие» задержки, которые мы используем внутри репостера,
чтобы телеграм‑клиент выглядел менее роботизированным.

* `human_delay()` – синхронное: возвращает случайное число секунд.
* `async_sleep_human()` – асинхронное: реально спит указанное время.
"""

from __future__ import annotations

import asyncio
import random


def human_delay(min_sec: float = 0.6, max_sec: float = 2.2) -> float:
    """
    Вернуть случайную задержку в диапазоне **[min_sec, max_sec]**.

    Используется в логике репоста, чтобы распределить нагрузку
    и имитировать естественные паузы между действиями.

    :param min_sec: минимальная задержка (сек)
    :param max_sec: максимальная задержка (сек)
    :return: число секунд (float)
    """
    if min_sec >= max_sec:
        raise ValueError("min_sec должно быть меньше max_sec")
    return random.uniform(min_sec, max_sec)


async def async_sleep_human(min_sec: float = 0.6, max_sec: float = 2.2) -> None:
    """
    Асинхронный `sleep` с человеческим рандом.

    Пример::

        await async_sleep_human()  # пауза ~0.8–2.0 c

    :param min_sec: минимальная задержка (сек)
    :param max_sec: максимальная задержка (сек)
    """
    await asyncio.sleep(human_delay(min_sec, max_sec))
