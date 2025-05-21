from pathlib import Path
import asyncio

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from hydra_reposter.core.accounts_service import LolzMarketClient, LolzApiError
from hydra_reposter.core.proxy_service import ProxyManager
from hydra_reposter.core.config import settings


async def login_account(
    session_path: Path, proxy: tuple = None, item_id: int | None = None
) -> TelegramClient:
    """
    Авторизует клиент Telethon по файлу сессии и прокси.
    Если клиент не авторизован, пытается получить код через LolzMarketClient.get_code(item_id).
    Возвращает готовый подключённый и авторизованный TelegramClient.
    """
    # Инициализация клиента с прокси
    client = TelegramClient(
        str(session_path), settings.api_id, settings.api_hash, proxy=proxy
    )
    await client.connect()

    # Если уже авторизован, возвращаем клиент
    if await client.is_user_authorized():
        return client

    # Если item_id не передан, невозможно получить код — отключаем и ошибка
    if item_id is None:
        await client.disconnect()
        raise RuntimeError(
            f"Session {session_path.name} не авторизован и нет item_id для получения кода."
        )

    # Получаем код из LolzMarketClient
    try:
        async with LolzMarketClient() as market:
            code = await market.get_code(item_id)
    except LolzApiError as e:
        await client.disconnect()
        raise RuntimeError(
            f"Не удалось получить код авторизации для {session_path.name}: {e}"
        )

    if not code:
        await client.disconnect()
        raise RuntimeError(f"Код авторизации для {session_path.name} не получен.")

    # Пытаемся войти по коду
    try:
        await client.sign_in(code=code)
    except SessionPasswordNeededError:
        # Если включена 2FA, используем пароль из settings.two_fa_password
        await client.sign_in(password=settings.two_fa_password)

    # После sign_in необходимо ещё раз проверить
    if not await client.is_user_authorized():
        await client.disconnect()
        raise RuntimeError(
            f"Авторизация не выполнена для {session_path.name} даже после ввода кода."
        )

    return client


def run_login_for_all(
    sessions: list[Path], proxies: list[tuple], item_ids: list[int]
) -> list[TelegramClient]:
    """
    Последовательно логинит список аккаунтов с привязкой прокси и item_id.
    Возвращает список авторизованных TelegramClient.
    """
    clients: list[TelegramClient] = []

    async def _run_all():
        pm = ProxyManager()
        for session_path, item_id in zip(sessions, item_ids):
            proxy = await pm.acquire()
            client = await login_account(session_path, proxy, item_id)
            clients.append(client)
        await pm.aclose()

    asyncio.run(_run_all())
    return clients
