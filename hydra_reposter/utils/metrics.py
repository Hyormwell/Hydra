"""
hydra_reposter.utils.metrics
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Простейший in‑memory счётчик событий, пригодный для вывода
в CLI‑«dashboard» и для unit‑тестов.

Используем обычный `dict[str, int]` + функции‑обёртки — этого
достаточно, чтобы собирать статистику в рамках одного процесса.

Если в будущем понадобится Prometheus / InfluxDB, можно заменить
имплементацию, сохранив тот же API.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Dict

# защищаем структуру от гонок в asyncio‑контексте
_lock = threading.Lock()
_metrics: Dict[str, int] = defaultdict(int)


def inc_metric(name: str, value: int = 1) -> None:
    """
    Увеличить метрику *name* на *value*.

    Пример::

        inc_metric("sent")
        inc_metric("peer_flood", 3)
    """
    with _lock:
        _metrics[name] += value


def get_metric(name: str) -> int:
    """
    Вернуть текущее значение метрики или 0, если она ещё не создавалась.
    """
    with _lock:
        return _metrics.get(name, 0)


def snapshot() -> dict[str, int]:
    """
    Получить копию всех метрик (для вывода в dashboard или тестов).
    """
    with _lock:
        return dict(_metrics)


def reset_metrics() -> None:
    """
    Сбросить все значения в 0 (используется в тестах).
    """
    with _lock:
        _metrics.clear()
