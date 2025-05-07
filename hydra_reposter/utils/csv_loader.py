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

    :param path: путь к CSV‑файлу.
    :param encoding: кодировка файла (по умолчанию UTF‑8).
    :return: список строк без пустых элементов и пробелов.
    """
    if not path.exists():
        raise FileNotFoundError(f"CSV‑файл '{path}' не найден")

    targets: List[str] = []
    with path.open(newline="", encoding=encoding) as fp:
        reader = csv.reader(fp)
        for raw_row in reader:
            if not raw_row:
                # пустая строка
                continue

            first_cell: str = raw_row[0].strip()
            # пропускаем заголовок CSV
            if first_cell.upper() == "ID":
                continue
            # пропускаем комментарии и пустые ячейки
            if not first_cell or first_cell.startswith("#"):
                continue

            targets.append(first_cell)

    if not targets:
        raise ValueError(f"CSV‑файл '{path}' не содержит валидных целей")

    return targets
