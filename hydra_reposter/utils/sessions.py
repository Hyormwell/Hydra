from pathlib import Path
from typing import List
from telethon import TelegramClient
from telethon.sessions import StringSession
import shutil
import asyncio
from telethon import errors
from hydra_reposter.core.accounts_service import LolzMarketClient, LolzApiError
from hydra_reposter.core.db import get_session, Account, init_db
from hydra_reposter.core import settings
from rich.console import Console
from hydra_reposter.utils.quarantine import is_quarantined

console = Console()
DEAD_DIR = Path(settings.sessions_dir) / "dead_sessions"
DEAD_DIR.mkdir(exist_ok=True)

def ensure_account(db, item_id, session_path):
    acc = db.query(Account).filter(Account.item_id == item_id).first()
    if not acc:
        acc = Account(
            phone=f"tg://{item_id}",
            proxy_id=None,
            status="unknown",
            session_path=session_path,
            item_id=item_id
        )
        db.add(acc); db.commit(); db.refresh(acc)
    return acc

async def test_auth(path):
    client = TelegramClient(str(path), settings.api_id, settings.api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        raise errors.AuthKeyError("Unauthorized")
    me = await client.get_me()
    await client.disconnect()
    return me

async def run_session_check():
    init_db()
    db = get_session()
    sessions_dir = Path(settings.sessions_dir)
    ok = bad = 0
    for sess_path in sessions_dir.glob("*.session"):
        fname = sess_path.name
        if is_quarantined(sess_path):
            continue
        item_id = int(sess_path.stem)
        rec = ensure_account(db, item_id, str(sess_path))
        lolz = LolzMarketClient()

        try:
            # First attempt: normal session connect
            me = await test_auth(sess_path)
            console.print(f"[green]OK[/] {fname} — @{me.username or me.id}")
            rec.status = "ok"
            ok += 1
        except Exception:
            # Need to login via Telethon
            console.print(f"[yellow]Attempting Telethon login for {fname}[/]")
            client = TelegramClient(StringSession(), settings.api_id, settings.api_hash)
            await client.connect()
            try:
                # Fetch login and password from Lolz API
                try:
                    account_info = await lolz.get_account(item_id=item_id)
                    # Extract the actual item data
                    item_data = account_info.get('item', {})
                    # Try common fields for phone/login
                    phone = item_data.get('login') or item_data.get('phone') or item_data.get('username')
                    password = item_data.get('password')
                    if not phone:
                        console.print(f"[red]No phone/login returned for {fname}. Item keys: {list(item_data.keys())}[/]")
                        rec.status = "fail"; bad += 1
                        shutil.move(sess_path, DEAD_DIR / fname)
                        db.add(rec); db.commit()
                        continue
                except Exception as acc_err:
                    console.print(f"[red]Failed to fetch account info for {fname}: {acc_err}[/]")
                    rec.status = "fail"; bad += 1
                    shutil.move(sess_path, DEAD_DIR / fname)
                    db.add(rec); db.commit()
                    continue

                # request login via phone number
                await client.send_code_request(phone)
                code = await lolz.get_code(item_id=item_id)
                await client.sign_in(phone, code)
            except errors.SessionPasswordNeededError:
                # 2FA password needed
                if password:
                    await client.sign_in(password=password)
                else:
                    console.print(f"[red]2FA password needed but no password provided for {fname}[/]")
                    rec.status = "fail"
                    bad += 1
                    shutil.move(sess_path, DEAD_DIR / fname)
                    db.add(rec); db.commit()
                    await client.disconnect()
                    continue
            except Exception as login_err:
                console.print(f"[red]Login failed for {fname}: {login_err}[/]")
                rec.status = "fail"
                bad += 1
                shutil.move(sess_path, DEAD_DIR / fname)
                db.add(rec); db.commit()
                await client.disconnect()
                continue
            # on success, save session to disk
            client.session.save(str(sess_path))
            me = await client.get_me()
            console.print(f"[green]Authorized[/] {fname} — @{me.username or me.id}")
            rec.status = "ok"; ok += 1
            db.add(rec); db.commit()
            await client.disconnect()

        db.add(rec); db.commit()

    console.print(f"\nИтого: OK {ok}, Ошибок {bad}")


# --- Заглушки для совместимости с репостером ---
async def load_live_clients(sessions_dir: Path) -> List[TelegramClient]:
    """
    Заглушка для совместимости с репостером.
    При необходимости, заменить на реальную логику загрузки и авторизации клиентов.
    """
    return []

async def resolve_donor(client: TelegramClient, donor_link: str) -> str:
    """
    Заглушка для совместимости с репостером.
    При необходимости, реализовать получение финального имени канала.
    """
    return donor_link