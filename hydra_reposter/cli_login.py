import asyncio, shutil
from pathlib import Path
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from hydra_reposter.core import settings

SESS_DIR = Path("sessions")
DEAD_DIR = Path("dead_sessions"); DEAD_DIR.mkdir(exist_ok=True)

async def fix_session(sess: Path):
    client = TelegramClient(str(sess), settings.api_id, settings.api_hash)
    try:
        await client.connect()
        if await client.is_user_authorized():
            print(f"✔ {sess.name}: уже авторизован")
        else:
            phone = input(f"Номер, которому принадлежит {sess.name}: ")
            await client.send_code_request(phone)
            code = input("Код из Telegram: ")
            try:
                await client.sign_in(phone, code)
            except SessionPasswordNeededError:
                pwd = input("Пароль 2FA: ")
                await client.sign_in(password=pwd)
            print(f"✓ {sess.name}: перелогинен")
    except Exception as e:
        print(f"✘ {sess.name}: {e}")
        await client.disconnect()
        shutil.move(sess, DEAD_DIR / sess.name)
    else:
        await client.disconnect()

async def main():
    files = list(SESS_DIR.glob("*.session"))
    if not files:
        print("Файлы .session не найдены")
        return
    for f in files:
        await fix_session(f)

if __name__ == "__main__":
    asyncio.run(main())