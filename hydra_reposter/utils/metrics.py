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

# --------------------------------------------------------------------------- #
# Optional Prometheus integration constants / stubs
# --------------------------------------------------------------------------- #
try:
    from prometheus_client import Gauge, start_http_server  # type: ignore
except ModuleNotFoundError:
    # Prometheus client library not installed – define minimal stubs
    Gauge = None  # type: ignore
    def start_http_server(port: int) -> None:  # type: ignore
        return

_DEFAULT_PORT: int = 8000
_started_flag: bool = False
# keep a dict for Prometheus gauges if the lib is present
_COUNTERS: Dict[str, "Gauge"] = {}

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


# hydra_reposter/utils/metrics.py
# (Assuming the rest of the file is unchanged and we append the shim at the end)

# --------------------------------------------------------------------------- #
# Backward-compatibility shim
# --------------------------------------------------------------------------- #
# Some legacy modules expect start_metrics and set_gauge to exist. Provide
# thin wrappers if they are missing (e.g., when this file was imported
# before the functions were defined above).
if "start_metrics" not in globals():
    def start_metrics(port: int = _DEFAULT_PORT) -> None:  # type: ignore
        """Start the Prometheus HTTP endpoint (idempotent, no‑op if unavailable)."""
        global _started_flag
        if start_http_server is None:
            return  # Prometheus not available – silently skip
        with _lock:
            if _started_flag:
                return
            start_http_server(port)
            _started_flag = True

if "set_gauge" not in globals():
    def set_gauge(name: str, value: float) -> None:  # type: ignore
        if Gauge is None:
            return  # no-op when Prometheus is missing
        metric = _COUNTERS.get(name)
        if metric and isinstance(metric, Gauge):
            metric.set(value)
