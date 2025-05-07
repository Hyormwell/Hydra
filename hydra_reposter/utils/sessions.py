# hydra_reposter/utils/sessions.py
from __future__ import annotations
import shutil, time
from pathlib import Path
from typing import List
from telethon import TelegramClient
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.errors import SessionPasswordNeededError, UserAlreadyParticipantError
from hydra_reposter.core.config import settings
from hydra_reposter.core.errors import AuthRequired
from hydra_reposter.utils.quarantine import is_quarantined, add_quarantine

DEAD_DIR = Path("dead_sessions")
DEAD_DIR.mkdir(exist_ok=True)

async def load_live_clients(sessions_dir: Path) -> List[TelegramClient]:
    clients: List[TelegramClient] = []
    for sess_path in sessions_dir.glob("*.session"):
        if is_quarantined(sess_path):
            continue
        client = TelegramClient(str(sess_path), settings.api_id, settings.api_hash)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                raise AuthRequired("not authorised")
            clients.append(client)
        except AuthRequired:
            # переносим пустой файл, чтобы не мешался
            await client.disconnect() #Закрываем
            shutil.move(sess_path, DEAD_DIR / sess_path.name) #Переносим
        except SessionPasswordNeededError:
            # аккаунт защищён 2FA — бесполезен для авто-спама
            await client.disconnect()  # Закрываем
            shutil.move(sess_path, DEAD_DIR / sess_path.name)  # Переносим
    return clients

async def resolve_donor(client: TelegramClient, donor_link: str):
    """
    Принимает invite-ссылку «https://t.me/+Abc...», если нужно — вступает,
    и возвращает InputPeer донор-канала.
    """
    if "+".encode() in donor_link.encode():
        hash_ = donor_link.rsplit("+", maxsplit=1)[-1]
        try:
            await client(ImportChatInviteRequest(hash_))
        except UserAlreadyParticipantError:
            pass
    return await client.get_input_entity(donor_link)