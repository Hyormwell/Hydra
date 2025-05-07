"""
hydra_reposter.utils.quarantine
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Утилита для пометки Telegram‑сессий «карантином», если аккаунт
вызвал жёсткую ошибку (PeerFlood, долгий FloodWait и т.п.).

* Хранилище — JSON-файл ``quarantine.json`` в корне проекта.
* Формат::

    {
        "<session_path>": {
            "until": 1714768800,   # UNIX‑время, когда карантин истекает
            "reason": "PeerFlood"
        },
        ...
    }

* TTL по умолчанию — 24 часа (можно настроить через settings).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, TypedDict

from hydra_reposter.core.config import settings

_QUARANTINE_FILE = Path("quarantine.json")
_DEFAULT_TTL = 60 * 60 * 24  # 24h


class QuarantineEntry(TypedDict):
    until: int      # Unix‑timestamp
    reason: str


def _load() -> Dict[str, QuarantineEntry]:
    if _QUARANTINE_FILE.exists():
        try:
            return json.loads(_QUARANTINE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:  # повреждённый файл
            _QUARANTINE_FILE.unlink(missing_ok=True)
    return {}


def _save(data: Dict[str, QuarantineEntry]) -> None:
    _QUARANTINE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_quarantine(session: Path, reason: str = "unknown", ttl: int | None = None) -> None:
    """
    Поместить сессию в карантин **ttl** секунд (по умолчанию 24h).
    """
    ttl = ttl or _DEFAULT_TTL
    data = _load()
    data[str(session)] = {"until": int(time.time()) + ttl, "reason": reason}
    _save(data)


def is_quarantined(session: Path) -> bool:
    """
    Проверить, находится ли сессия в карантине.
    Просроченные записи автоматически удаляются.
    """
    data = _load()
    entry = data.get(str(session))
    if not entry:
        return False

    if entry["until"] < time.time():
        # карантин истёк — чистим запись
        del data[str(session)]
        _save(data)
        return False
    return True


def clear_expired() -> None:
    """
    Удалить все просроченные карантины.
    """
    data = _load()
    now = time.time()
    changed = False
    for key, entry in list(data.items()):
        if entry["until"] < now:
            del data[key]
            changed = True
    if changed:
        _save(data)
