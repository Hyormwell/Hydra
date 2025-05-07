# hydra_reposter/core/client.py
from contextlib import asynccontextmanager
from pathlib import Path
from telethon import TelegramClient
from hydra_reposter.core.config import settings
from hydra_reposter.core.errors import AuthRequired

@asynccontextmanager
async def telegram_client(session_file: Path):
    if not settings.api_id or not settings.api_hash:
        raise RuntimeError("API_ID / API_HASH не заданы")

    client = TelegramClient(
        str(session_file),
        settings.api_id,
        settings.api_hash,
    )
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise AuthRequired(f"{session_file.name} не авторизована")
        yield client                     # ← отдаём наружу
    finally:
        await client.disconnect()