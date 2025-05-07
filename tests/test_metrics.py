"""
Тесты для hydra_reposter.utils.metrics
"""

import pytest

from hydra_reposter.utils.metrics import (
    inc_metric,
    get_metric,
    snapshot,
    reset_metrics,
)


def test_increment_and_get():
    """
    inc_metric должен увеличивать счётчик,
    а get_metric — возвращать актуальное значение.
    """
    reset_metrics()
    assert get_metric("sent") == 0

    inc_metric("sent")
    assert get_metric("sent") == 1

    inc_metric("sent", 4)
    assert get_metric("sent") == 5


def test_snapshot_is_copy():
    """
    snapshot возвращает копию, которую невозможно
    изменить через оригинальные счётчики.
    """
    reset_metrics()
    inc_metric("peer_flood", 2)

    snap = snapshot()
    assert snap == {"peer_flood": 2}

    # Мутируем оригинальную метрику
    inc_metric("peer_flood")
    # Снимок должен остаться прежним
    assert snap == {"peer_flood": 2}
    # Новый снимок уже отражает изменение
    assert snapshot()["peer_flood"] == 3


def test_reset_metrics():
    """
    reset_metrics должен обнулять все значения.
    """
    reset_metrics()
    inc_metric("skipped", 3)
    assert get_metric("skipped") == 3

    reset_metrics()
    assert get_metric("skipped") == 0