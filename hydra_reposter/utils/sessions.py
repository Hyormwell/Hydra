# hydra_reposter/utils/sessions.py
from __future__ import annotations
import shutil, time
from pathlib import Path
from typing import List
from telethon import TelegramClient
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.errors import SessionPasswordNeededError, UserAlreadyParticipantError
from hydra_reposter.core import settings
from hydra_reposter.core.errors import AuthRequired
from hydra_reposter.utils.quarantine import is_quarantined, add_quarantine
from hydra_reposter.core.accounts_service import LolzMarketClient, LolzApiError
from hydra_reposter.core.db import get_session, Account
from rich.console import Console
console = Console()

DEAD_DIR = Path("dead_sessions")
DEAD_DIR.mkdir(exist_ok=True)

async def load_live_clients(sessions_dir: Path) -> List[TelegramClient]:
    db = get_session()
    clients: List[TelegramClient] = []
    for sess_path in sessions_dir.glob("*.session"):
        fname = sess_path.name
        if is_quarantined(sess_path):
            continue
        lolz = LolzMarketClient()
        client = TelegramClient(str(sess_path), settings.api_id, settings.api_hash)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                # Try to authorize via Lolz API
                try:
                    code = lolz.get_code(item_id=Path(sess_path).stem)
                    await client.sign_in(code=code)
                except LolzApiError as api_err:
                    raise AuthRequired(f"lolz API failed: {api_err}")
                if not await client.is_user_authorized():
                    raise AuthRequired("authorization failed after code")
            clients.append(client)
        except AuthRequired:
            # Attempt to authorize session using Lolz API code
            item_id = int(sess_path.stem)
            rec = db.query(Account).filter(Account.item_id == item_id).first()
            try:
                code = lolz.get_code(item_id=item_id)
                console.print(f"[blue]Signing in {fname} with code from Lolz API[/]")
                await client.sign_in(code=code)
                if await client.is_user_authorized():
                    console.print(f"[green]Authorized[/] {fname} after code")
                    rec.status = "ok"
                    db.add(rec)
                    db.commit()
                    clients.append(client)
                    continue  # move to next session
                else:
                    raise AuthRequired("authorization failed after API code")
            except LolzApiError as api_err:
                console.print(f"[red]Lolz API error for {fname}: {api_err}[/]")
            except Exception as auth_err:
                console.print(f"[red]Auth retry failed for {fname}: {auth_err}[/]")

            # If we reach here, authorization failed—mark and move to dead
            rec.status = "fail"
            db.add(rec); db.commit()
            await client.disconnect()
            shutil.move(sess_path, DEAD_DIR / fname)
            console.print(f"[yellow]Moved invalid session to dead: {fname}[/]")
        except SessionPasswordNeededError:
            # Mark session as 2FA protected in DB
            item_id = int(sess_path.stem)
            rec = db.query(Account).filter(Account.item_id == item_id).first()
            if rec:
                rec.status = "2fa_protected"
                db.add(rec)
                db.commit()
            # аккаунт защищён 2FA — бесполезен для авто-спама
            await client.disconnect()  # Закрываем
            shutil.move(sess_path, DEAD_DIR / fname)  # Переносим
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