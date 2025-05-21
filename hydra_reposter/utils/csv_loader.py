"""
hydra_reposter.utils.csv_loader
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Мини‑утилита для чтения списка целевых чатов/каналов/пользователей из CSV‑файла.

CSV‑формат поддерживает несколько вариантов:

1. **Одиночная колонка** – каждый элемент на новой строке.
2. **Много колонок** – читается **первая** ячейка каждой строки.
3. Комментарии с `#` в начале строки игнорируются.
4. Пустые строки и пробелы обрезаются.

Функция **load_targets_from_csv** возвращает `list[str]` уже очищенных
username/ID, готовых для передачи в репостер.

Пример::

    >>> from pathlib import Path
    >>> from hydra_reposter.utils.csv_loader import load_targets_from_csv
    >>> targets = load_targets_from_csv(Path("targets.csv"))
    >>> print(targets)
    ['@channel1', '@channel2', 'https://t.me/some_chat']
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import List


def load_targets_from_csv(path: Path, encoding: str = "utf-8") -> List[str]:
    """
    Загрузить список целей из CSV.

    Функция больше не зависит от расположения колонки.
    Поддерживаются следующие форматы ячеек:

    * `@username`
    * `https://t.me/username`  /  `t.me/username`
    * `+inviteHash`            (инвайт‑ссылки без домена)
    * целочисленный ID (например `123456789`)

    При чтении:
      * обрезаются пробелы;
      * пропускаются строки‑комментарии (`# …`);
      * пропускаются ряды, содержащие только заголовки
        (`ID`, `USERNAME`, `ЮЗЕРНЕЙМ`, `USER`, `link`, в любом регистре).

    :param path: путь к CSV‑файлу.
    :param encoding: кодировка файла (по умолчанию UTF‑8).
    :return: список целей (str).
    """
    if not path.exists():
        raise FileNotFoundError(f"CSV‑файл '{path}' не найден")

    targets: List[str] = []

    # набор ключевых слов, по которым можно понять, что это строка‑заголовок
    _header_tokens = {"ID", "USERNAME", "USER", "ЮЗЕРНЕЙМ", "ЮЗЕРНЭЙМ", "LINK", "URL"}

    with path.open(newline="", encoding=encoding) as fp:
        reader = csv.reader(fp)
        for raw_row in reader:
            # убираем пустые и обрезаем пробелы
            cells = [c.strip() for c in raw_row if c and c.strip()]
            if not cells:
                continue  # пустая строка

            # Если вся строка состоит из заголовков – пропускаем
            if all(c.upper() in _header_tokens for c in cells):
                continue

            for cell in cells:
                # комментарий?
                if cell.startswith("#"):
                    break

                # допустимые форматы цели
                if (
                    cell.startswith("@")                           # @username
                    or cell.startswith("http://")                  # ссылка
                    or cell.startswith("https://")
                    or cell.startswith("t.me/")
                    or cell.lstrip("+").isdigit()                  # numeric id / +hash
                ):
                    targets.append(cell)
                    break  # берем только одну цель из строки

    if not targets:
        raise ValueError(f"CSV‑файл '{path}' не содержит валидных целей")

    return targets
