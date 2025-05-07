# hydra_reposter/core/errors.py
"""
Доменные ошибки Hydra Reposter.

Каждый класс - тонкая оболочка над стандартным Exception.
Иерархия упрощает `except`-блоки в workers:
    except FloodWaitSoft | FloodWaitHard: ...
"""

class ReposterError(Exception):
    """Базовый класс для всех ошибок репостера."""


# ----- FloodWait -----------------------------------------------------------
class FloodWaitBase(ReposterError):
    """Родитель для soft/hard FloodWait; содержит время ожидания."""

    def __init__(self, wait_seconds: int, *args):
        super().__init__(*args)
        self.wait_seconds = wait_seconds

    def __str__(self) -> str:  # удобный вывод
        return f"{self.__class__.__name__}: wait {self.wait_seconds}s"


class FloodWaitSoft(FloodWaitBase):
    """Короткий FloodWait (< floodwait_threshold)."""


class FloodWaitHard(FloodWaitBase):
    """Длинный FloodWait (>= floodwait_threshold)."""


# ----- PeerFlood / SpamBlock ----------------------------------------------
class PeerFlood(ReposterError):
    """Телеграм отфутболил акк как «слишком много запросов к юзерам»."""


# ----- Privacy / Forbidden -------------------------------------------------
class PrivacySkip(ReposterError):
    """Нельзя писать юзеру из-за privacy-настроек."""


class ChatWriteForbidden(ReposterError):
    """Боту/акку запрещено писать в чат/канал."""


# ----- Прочее --------------------------------------------------------------
class AuthRequired(ReposterError):
    """Сессия не авторизована (account.login() не сделан)."""


class AccountBanned(ReposterError):
    """Аккаунт деактивирован или забанен."""