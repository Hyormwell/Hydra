from pathlib import Path
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import AuthKeyDuplicatedError
from telethon.crypto.authkey import AuthKey
import time
from typing import List
import httpx  # low‑level fallback for direct REST calls
import shutil
import asyncio
import json

# ensure pretty JSON dumps in debug output
import os
import re
import base64
from hydra_reposter.core.db import Account
from hydra_reposter.core import settings
from rich.console import Console
from hydra_reposter.utils.quarantine import is_quarantined

console = Console()

# --- LOLZ Market HTTP helper ---
API_BASE = "https://api.zelenka.guru/market"

API_TOKEN = settings.lolz_api_key or os.getenv("LOLZ_API_KEY")
# LOLZ Market REST API expects either
#   ?key=<token>  _or_  Authorization: Bearer <token>
# Authorisation header is less error‑prone (doesn’t get lost on redirects)
HEADERS = {"Authorization": f"Bearer {API_TOKEN}"} if API_TOKEN else {}

# allow only one concurrent LOLZ‑API request
SEM = asyncio.Semaphore(1)


async def api_get(path: str, *, tries: int = 5) -> dict:
    """
    GET {API_BASE}/{path} c учётом лимитов и повторов при 429.

    • удерживаем глобальный семафор, чтобы не посылать параллельно;
    • после каждого запроса ждём 2с (await asyncio.sleep(2));
    • если получаем 429 — читаем Retry‑After или ждём 2**n секунд.
    """
    url = f"{API_BASE}/{path.lstrip('/')}"
    # bust Cloudflare / CDN cache to reduce stale payloads
    if "?v=" not in url:
        delim = "&" if "?" in url else "?"
        url = f"{url}{delim}v={int(time.time())}"
    # Always pass the API token as ?key=... too – some Market endpoints
    # ignore the Authorization header on redirects/CDN edges.
    if API_TOKEN and "key=" not in url:
        delimiter = "&" if "?" in url else "?"
        url = f"{url}{delimiter}key={API_TOKEN}"
    for attempt in range(tries):
        async with SEM:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(url, headers=HEADERS)
            # пауза 1.2 с внутри семафора — гарантирует <0.5 rps
            await asyncio.sleep(1.2)

        if resp.status_code == 429 and attempt < tries - 1:
            wait = int(resp.headers.get("Retry-After", 2**attempt))
            await asyncio.sleep(wait)
            continue
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            console.print(
                f"[red][LOLZ API ERROR] {e.response.status_code} on {url}[/red]"
            )
            return {}
        except Exception as e:
            console.print(f"[red][LOLZ API ERROR] {e}[/red]")
            return {}
        return resp.json()
    return {}


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
            item_id=item_id,
        )
        db.add(acc)
        db.commit()
        db.refresh(acc)
    return acc


async def fetch_account_info(item_id: int) -> dict:
    """
    Return phone / password / auth_key / dc_id for a Market lot.

    1. Tries the dedicated `/accounts/{id}` endpoint that already returns a
       normalised structure with `telegram_json` inside.
    2. Falls back to the older `/items/{id}?with=telegram_json` variant.
    3. Handles occasional responses wrapped in a one‑element list.
    """
    if not API_TOKEN:
        console.print(
            f"[yellow]LOLZ_API_KEY not set – cannot request lot {item_id}[/yellow]"
        )
        return {}

    # 1) preferred endpoint
    raw = await api_get(f"accounts/{item_id}")
    # 2) legacy fallback
    if not raw:
        raw = await api_get(f"items/{item_id}?with=telegram_json")

    # skip archived / deleted lots early
    state = raw.get("state") or raw.get("item", {}).get("state")
    if state == "deleted":
        return {}

    # some endpoints may respond with `[{}]`
    if isinstance(raw, list):
        raw = raw[0] if raw else {}

    # locate telegram_json blob
    tg_raw = (
        raw.get("telegram_json")
        or raw.get("item", {}).get("telegram_json")
        or raw.get("data", {}).get("telegram_json")
        or {}
    )
    if not isinstance(tg_raw, dict):
        try:
            tg_raw = json.loads(tg_raw or "{}")
        except json.JSONDecodeError:
            tg_raw = {}

    # debug dump of the first 500 bytes when critical fields are missing
    if getattr(settings, "debug", False) and not tg_raw.get("auth_key"):
        console.print(
            f"[blue][DEBUG] Raw API payload for lot {item_id}: "
            f"{json.dumps(raw)[:500]}[/blue]"
        )

    title = raw.get("title") or raw.get("item", {}).get("title")
    price = raw.get("price") or raw.get("item", {}).get("price")

    # --- normalise fields -------------------------------------------------
    # helper that returns first non‑empty value
    def _pick(*variants):
        return next((v for v in variants if v not in (None, "", [], {})), None)

    phone = _pick(
        tg_raw.get("phone"),
        tg_raw.get("login"),
        tg_raw.get("username"),
        raw.get("phone"),
        raw.get("login"),
    )

    password = _pick(
        tg_raw.get("password"),
        tg_raw.get("pass"),
        raw.get("password"),
    )

    auth_key_hex = _pick(
        tg_raw.get("auth_key_hex"),
        raw.get("auth_key_hex"),
    )
    auth_key = _pick(
        tg_raw.get("auth_key"),
        tg_raw.get("authkey"),
        raw.get("auth_key"),
        raw.get("authkey"),
    )

    dc_id = _pick(
        tg_raw.get("dc_id"),
        tg_raw.get("dc"),
        tg_raw.get("dcId"),
        raw.get("dc_id"),
        raw.get("dc"),
    )

    # LOLZ Market sometimes returns auth_key as 256‑char hex – convert to b64
    if auth_key and re.fullmatch(r"[0-9a-fA-F]{256}", auth_key):
        auth_key = base64.b64encode(bytes.fromhex(auth_key)).decode()

    return {
        "phone": phone,
        "password": password,
        "auth_key": auth_key,
        "auth_key_hex": auth_key_hex,
        "dc_id": dc_id,
        "title": title,
        "price": price,
    }


async def login_with_auth_key(
    item_id: int, sess_path: Path, api_id: int, api_hash: str
) -> bool:
    try:
        info = await fetch_account_info(item_id)
    except Exception as e:
        console.print(
            f"[red][LOLZ API ERROR] Ошибка при получении данных аккаунта {item_id}: {e}[/red]"
        )
        return False
    auth_key_hex = info.get("auth_key_hex")
    auth_key_b64 = info.get("auth_key")
    dc_id = info.get("dc_id")

    # prefer HEX key when available
    if auth_key_hex and re.fullmatch(r"[0-9a-fA-F]{256}", auth_key_hex):
        sess = StringSession("")
        sess._auth_key = AuthKey(bytes.fromhex(auth_key_hex))
        key_descr = "hex"
    else:
        if not auth_key_b64:
            console.print(
                f"[yellow]Недостаточно данных для входа по auth_key для аккаунта "
                f"{item_id} ({info.get('title','?')}/{info.get('price','?')})[/yellow]"
            )
            # extra verbose dump when debug flag is enabled
            if getattr(settings, "debug", False):
                console.print(
                    f"[blue][DEBUG] Полный info для лота {item_id}: {json.dumps(info, ensure_ascii=False)[:800]}[/blue]"
                )
            return False
        sess = StringSession(auth_key_b64)
        key_descr = "base64"

    if not dc_id:
        console.print(
            f"[yellow]Не указан dc_id в лоте {item_id} ({info.get('title','?')})[/yellow]"
        )
        return False

    try:
        client = TelegramClient(sess, api_id, api_hash, dc_id=dc_id)
        await client.connect()
        if await client.is_user_authorized():
            client.session.save(str(sess_path))
            await client.disconnect()
            return True
        await client.disconnect()
    except AuthKeyDuplicatedError:
        console.print(
            f"[yellow]AuthKeyDuplicatedError — ключ {key_descr} для {item_id} уже активен[/yellow]"
        )
        return True
    except Exception as e:
        console.print(
            f"[red]Ошибка при входе по auth_key для аккаунта {item_id}: {e}[/red]"
        )
    return False


async def login_with_phone_code(
    item_id: int, sess_path: Path, api_id: int, api_hash: str
) -> bool:
    try:
        info = await fetch_account_info(item_id)
    except Exception as e:
        console.print(
            f"[red][LOLZ API ERROR] Ошибка при получении данных аккаунта {item_id}: {e}[/red]"
        )
        return False
    phone = info.get("phone")
    #password = info.get("password")

    if not phone:
        console.print(
            f"[yellow]Отсутствует номер телефона для аккаунта {item_id} ({info.get('title','?')})[/yellow]"
        )
        if getattr(settings, "debug", False):
            console.print(
                f"[blue][DEBUG] Полный info для лота {item_id}: {json.dumps(info, ensure_ascii=False)[:800]}[/blue]"
            )
        return False

    try:
        client = TelegramClient(StringSession(), api_id, api_hash)
        await client.connect()
        await client.send_code_request(phone)
        # Логин‑коды для лота доступны отдельным запросом
        code_url = f"{API_BASE}/items/{item_id}/code"
        async with httpx.AsyncClient(timeout=10) as client_aclose:
            resp = await client_aclose.get(code_url, headers=HEADERS)
            if resp.status_code != 200:
                console.print(
                    f"[yellow]Код подтверждения не получен for lot {item_id}[/yellow]"
                )
                await client_aclose.aclose()
                await client.disconnect()
                return False
            code = resp.json().get("code")
        if not code:
            console.print(
                f"[yellow]Не удалось получить код подтверждения для аккаунта {item_id}[/yellow]"
            )
            await client.disconnect()
            return False
        await client.sign_in(phone, code)
        if await client.is_user_authorized():
            client.session.save(str(sess_path))
            await client.disconnect()
            return True
        await client.disconnect()
    except Exception as e:
        console.print(
            f"[red]Ошибка при входе по коду для аккаунта {item_id}: {e}[/red]"
        )
    return False


async def test_auth(path):
    client = TelegramClient(str(path), settings.api_id, settings.api_hash)
    try:
        await asyncio.wait_for(client.connect(), timeout=10)
        authorized = await asyncio.wait_for(client.is_user_authorized(), timeout=10)
        if not authorized:
            raise Exception("Unauthorized")
        me = await asyncio.wait_for(client.get_me(), timeout=10)
    finally:
        await client.disconnect()
    return me


async def run_session_check():
    from hydra_reposter.core.db import init_db, get_session

    init_db()

    db = get_session()
    sessions_dir = Path(settings.sessions_dir)
    ok = bad = 0
    for sess_path in sessions_dir.glob("*.session"):
        fname = sess_path.name
        if is_quarantined(sess_path):
            continue
        try:
            item_id = int(sess_path.stem)
        except ValueError:
            console.print(f"[yellow]Некорректное имя файла сессии: {fname}[/yellow]")
            continue
        rec = ensure_account(db, item_id, str(sess_path))

        try:
            me = await test_auth(sess_path)
            print(f"OK {fname} — @{me.username or me.id}")
            rec.status = "ok"
            ok += 1
        except Exception:
            try:
                if await login_with_auth_key(
                    item_id, sess_path, settings.api_id, settings.api_hash
                ):
                    print(f"OK {fname} — восстановлен через auth_key")
                    rec.status = "ok"
                    ok += 1
                    db.add(rec)
                    db.commit()
                    continue
            except Exception as e:
                console.print(
                    f"[red][LOLZ API ERROR] Ошибка при входе через auth_key для аккаунта {item_id}: {e}[/red]"
                )

            try:
                if await login_with_phone_code(
                    item_id, sess_path, settings.api_id, settings.api_hash
                ):
                    print(f"OK {fname} — вход по коду подтверждения")
                    rec.status = "ok"
                    ok += 1
                    db.add(rec)
                    db.commit()
                    continue
            except Exception as e:
                console.print(
                    f"[red][LOLZ API ERROR] Ошибка при входе по коду для аккаунта {item_id}: {e}[/red]"
                )
            if getattr(settings, "debug", False):
                try:
                    extra = await fetch_account_info(item_id)
                except Exception:
                    extra = {}
                console.print(
                    f"[blue][DEBUG] Лот {item_id}: "
                    f"{extra.get('title', '?')} / {extra.get('price', '?')}[/blue]"
                )
            print(f"FAIL {fname} — все методы входа неудачны")
            rec.status = "fail"
            bad += 1
            shutil.move(sess_path, DEAD_DIR / fname)
            db.add(rec)
            db.commit()
            continue

        db.add(rec)
        db.commit()

    print(f"\nИтого: OK {ok}, Ошибок {bad}")


# --- Заглушки для совместимости с репостером ---
async def load_live_clients(sessions_dir: Path) -> List[TelegramClient]:
    clients: List[TelegramClient] = []
    for sess_file in sessions_dir.glob("*.session"):
        client = TelegramClient(str(sess_file), settings.api_id, settings.api_hash)
        await client.connect()
        if await client.is_user_authorized():
            clients.append(client)
        else:
            await client.disconnect()
    return clients


async def resolve_donor(client: TelegramClient, donor_link: str) -> str:
    """
    Заглушка для совместимости с репостером.
    При необходимости, реализовать получение финального имени канала.
    """
    return donor_link
