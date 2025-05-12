"""
Hydra Reposter CLI
~~~~~~~~~~~~~~~~~~
Typer-приложение с баннером а-ля TGSpammer и интерактивным меню.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional, List

from telethon import TelegramClient

from hydra_reposter.core.accounts_service import LolzMarketClient, LolzApiError
from hydra_reposter.core.proxy_service import ProxyManager, ProxyError

import typer
import httpx
from rich.console import Console
from rich.spinner import Spinner
from rich.panel import Panel
from rich.table import Table

from hydra_reposter.core import settings
from hydra_reposter.utils.csv_loader import load_targets_from_csv
from hydra_reposter.utils.metrics import get_metric, snapshot, reset_metrics
from hydra_reposter.utils.metrics import inc_metric  # для демо-отчёта
from hydra_reposter.utils.quarantine import is_quarantined
from hydra_reposter.workers.reposter import run_reposter


from hydra_reposter.core.db import init_db, get_session, Account

BASE_MARKET_URL = "https://prod-api.lzt.market"

async def find_item(price_rub_cents: int) -> tuple[int, float] | None:
    """
    Найти самый дешёвый авторег‑аккаунт без пароля/спамблока ≤ указанной цены.

    Parameters
    ----------
    price_rub_cents : int
        Порог цены в копейках (50 → 0.50₽).

    Returns
    -------
    (item_id, price) или None, если лотов нет.
    """
    import httpx
    params = {
        "sectionId": 151,
        "pmax": price_rub_cents,
        "filters[autorag]": 1,
        "filters[nopass]": 1,
        "filters[nospamblock]": 1,
        "sort": "price_to_up",
        "limit": 1,
    }
    async with httpx.AsyncClient(
        base_url=BASE_MARKET_URL,
        headers={"Authorization": f"Bearer {settings.lolz_token}"}
    ) as c:
        r = await c.get("/telegram", params=params, timeout=60.0)
        r.raise_for_status()
        items = r.json().get("items", [])
        if not items:
            return None
        itm = items[0]
        return itm["item_id"], float(itm["price"])


app = typer.Typer(add_completion=False, help="Hydra Reposter — модульная пересылка сообщений в Telegram")
console = Console()

DEFAULT_CSV = Path("data/targets.csv")
DEFAULT_DONOR = "https://t.me/+AtkcqZPW5kM1Y2Jl"  # значение по умолчанию – меняется только в коде
# --------------------------------------------------------------------------- #
#  Красивый баннер
# --------------------------------------------------------------------------- #
def print_banner() -> None:
    banner = r"""
   _   _       _            _____                       
  | | | | ___ | |__   ___  |  ___|__  _ __   ___  _ __  
  | |_| |/ _ \| '_ \ / _ \ | |_ / _ \| '_ \ / _ \| '_ \ 
  |  _  | (_) | |_) |  __/ |  _| (_) | | | | (_) | | | |
  |_| |_|\___/|_.__/ \___| |_|  \___/|_| |_|\___/|_| |_|

     H Y D R A   R E P O S T E R   v0.1
    """
    console.print(Panel.fit(banner, style="bold green"))


# --------------------------------------------------------------------------- #
#  Команды
# --------------------------------------------------------------------------- #
@app.command(help="Запустить перепост из CSV")
def send(
        donor: Optional[str] = typer.Option(None, "--donor", "-d", help="Ссылка на донор‑чат"),
        mode: str = typer.Option("slow", "--mode", "-m", help="Режим работы: slow|fast"),
        ids: List[int] = typer.Option([1], "--id", help="ID сообщений"),
        dry_run: bool = typer.Option(False, "--dry-run", help="Не отправлять сообщения, только лог"),
):
    """Команда: старт пересылки"""
    console.print(Spinner("dots", text="Загружаю CSV…"), end="\r")
    targets = [int(t) if str(t).isdigit() else t for t in load_targets_from_csv(DEFAULT_CSV)]
    # если донор не передан через CLI – используем константу
    donor = donor or DEFAULT_DONOR
    console.print(f"[bold cyan]Целей:[/] {len(targets)}")

    #Проверяем какие сессии активны
    sessions_dir = Path(settings.sessions_dir)  # ← есть в config

    sessions = [p for p in sessions_dir.glob("*.session") if not is_quarantined(p)]
    dead = len([p for p in sessions_dir.glob("*.session")]) - len(sessions)
    if dead:
        console.print(f"[yellow]Пропущено сессий (карантин/не авторизованы): {dead}[/]")

    # Запуск репостера
    if dry_run:
        console.print("[yellow]Dry‑run: сообщения не будут реально отправлены[/]")
    run_reposter(DEFAULT_CSV, donor, sessions_dir, mode, ids, dry_run=dry_run)

    console.print("\n[bold green]Готово![/]")
    console.print(f"Отправлено: {get_metric('sent')}, пропущено: {get_metric('skipped')}")


@app.command("check-sessions", help="Проверить авторизацию всех .session")
def check_sessions():
    init_db()
    db = get_session()
    sessions = list(Path(settings.sessions_dir).glob("*.session"))
    ok, bad = 0, 0

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
            db.add(acc)
            db.commit()
            db.refresh(acc)
        return acc

    async def test_auth(path):
        client = TelegramClient(str(path), settings.api_id, settings.api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            raise Exception("Unauthorized")
        me = await client.get_me()
        await client.disconnect()
        return me

    for sess_path in sessions:
        fname = sess_path.name
        item_id = int(fname.split(".")[0])
        rec = ensure_account(db, item_id, str(sess_path))

        try:
            # тестим авторизацию…
            me = asyncio.run(test_auth(sess_path))
            console.print(f"[green]OK[/] {fname} — @{me.username or me.id}")
            ok += 1
            rec.status = "ok"
            db.add(rec);
            db.commit()
        except Exception as e:
            console.print(f"[red]FAIL[/] {fname} — {e}")
            bad += 1
            rec.status = "fail"
            db.add(rec);
            db.commit()

        console.print(f"\nИтого: OK {ok}, Ошибок {bad}")


@app.command(help="Показать текущие метрики")
def dashboard():
    tbl = Table(title="Hydra Dashboard", show_edge=False, header_style="bold magenta")
    tbl.add_column("Метрика")
    tbl.add_column("Значение", justify="right")
    for k, v in snapshot().items():
        tbl.add_row(k, str(v))
    console.print(tbl)


@app.command(help="Конвертировать TD-данные → .session (заглушка)")
def convert(tdata: Path = typer.Argument(..., help="Файл tdata"), out: Path = typer.Argument(...)):
    console.print("[yellow]Функция конвертации будет добавлена позже.[/]")


# --------------------------------------------------------------------------- #
#  Sub-command group: accounts
# --------------------------------------------------------------------------- #
accounts_app = typer.Typer(name="accounts", help="Управление аккаунтами через LolzMarket API")
app.add_typer(accounts_app)

@accounts_app.command("buy", help="Купить N аккаунтов через LolzMarket API")
def accounts_buy(
    count: int = typer.Option(1, "--count", "-c", help="Количество аккаунтов для покупки")
):
    """
    Покупка аккаунтов.
    """
    console = Console()
    async def _buy():
        success = 0
        attempts = 0
        async with LolzMarketClient() as client:
            try:
                # крутим пока не купим нужное количество или не превысим лимит попыток
                while success < count and attempts < count * 6:
                    attempts += 1
                    try:
                        # определяем лот: берём из конфига или ищем самый дешёвый
                        if settings.market_item_id == 0:
                            found = await find_item(int(settings.market_price * 100))
                            if not found:
                                console.print("[yellow]Нет подходящих лотов по цене[/]")
                                break
                            item_id, real_price = found
                        else:
                            item_id = settings.market_item_id
                            real_price = settings.market_price

                        res = await client.fast_buy(
                            item_id=item_id,
                            price=real_price,
                        )
                        purchased = res.get("item", {})
                        console.print(
                            f"[green]Куплен аккаунт:[/] item_id={purchased.get('item_id')}, price={purchased.get('price', real_price)}"
                        )
                        # --- сохранить .session в папку sessions -----------------
                        try:
                            sess_bytes = await client.download_session(item_id)
                            sess_path = Path(settings.sessions_dir) / f"{item_id}.session"
                            sess_path.write_bytes(sess_bytes)
                            console.print(f"[blue]Сохранён .session → {sess_path.name}[/]")
                            # --- store in DB ---
                            with get_session() as db:
                                acc = Account(
                                    phone=f"tg://{purchased.get('item_id')}",
                                    proxy_id=None,
                                    status="purchased",
                                    session_path=str(sess_path),
                                    item_id=item_id
                                )
                                db.add(acc)
                                db.commit()
                            success += 1
                        except Exception as dl_err:
                            console.print(f"[yellow]Не удалось скачать .session:[/] {dl_err}")
                    except LolzApiError as e:
                        txt = str(e)
                        if "очереди на автоматическую покупку" in txt:
                            console.print("[yellow]Лот в авто‑очереди, пытаем другой через 1 с…[/]")
                            await asyncio.sleep(1)
                            continue
                        if "недостаточно средств" in txt:
                            console.print("[red]Недостаточно средств на балансе Market. Покупка остановлена.[/]")
                            break
                        console.print(f"[red]Ошибка покупки:[/] {e}")
                    except httpx.ReadTimeout:
                        console.print("[yellow]Timeout на запросе, повторяем позже…[/]")
                        continue
            except Exception as exc:
                console.print(f"[red]Непредвиденная ошибка при покупке:[/] {exc}")
            if success < count:
                console.print(f"[yellow]Не удалось купить все аккаунты "
                            f"({success}/{count}) после {attempts} попыток.[/]")
            console.print(f"Успешно куплено: {success}/{count}")
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None


    if loop and loop.is_running():
        loop.run_until_complete(_buy())
    else:
        asyncio.run(_buy())

@accounts_app.command("sync", help="Скачать сессии уже купленных аккаунтов")
def accounts_sync():
    """
    Проверяет профиль LolzMarket, скачивает .session всех купленных
    аккаунтов, которых нет в папке sessions.
    """
    console = Console()

    async def _sync():
        import httpx
        added = 0
        async with LolzMarketClient() as client:
            items = await client.list_paid_items()
            for itm in items:
                iid = itm["item_id"]
                sess_path = Path(settings.sessions_dir) / f"{iid}.session"
                if sess_path.exists():
                    continue  # уже есть
                try:
                    data = await client.download_session(iid)
                    sess_path.write_bytes(data)
                    console.print(f"[blue]Добавлен {sess_path.name} (price {itm['price']})[/]")
                    with get_session() as db:
                        acc = Account(
                            phone="unknown",
                            proxy_id=None,
                            status="synced",
                            session_path=str(sess_path),
                            item_id=iid
                        )
                        db.add(acc)
                        db.commit()
                    added += 1
                except Exception as err:
                    console.print(f"[yellow]Не скачан item {iid}: {err}[/]")

        console.print(f"[green]Синхронизация завершена. Файлов добавлено: {added}[/]")

    asyncio.run(_sync())

# --------------------------------------------------------------------------- #
#  Sub-command group: proxies
# --------------------------------------------------------------------------- #
proxies_app = typer.Typer(name="proxies", help="Управление прокси через ProxyManager")
app.add_typer(proxies_app)

@proxies_app.command("rotate", help="Поменять IP прокси")
def proxies_rotate(
    all: bool = typer.Option(False, "--all", "-a", help="Применить ко всем прокси")
):
    """
    Ротация прокси.
    """
    console = Console()
    async def _rotate():
        pm = ProxyManager()
        try:
            if all:
                # Ротация для всех прокси
                await pm.rotate_all()
                console.print("[green]Ротация всех прокси завершена успешно[/]")
            else:
                await pm.rotate()
                console.print("[green]Прокси IP сменён успешно[/]")
        except ProxyError as e:
            console.print(f"[red]Ошибка при ротации прокси:[/] {e}")
        finally:
            await pm.aclose()
    asyncio.run(_rotate())


# --------------------------------------------------------------------------- #
#  Root-callback: интерактивное меню
# --------------------------------------------------------------------------- #
@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    init_db()
    print_banner()
    if ctx.invoked_subcommand:
        return

    console.print("[bold]Выберите действие:[/]\n"
                  " [blue]1[/] — Запустить рассылку\n"
                  " [blue]2[/] — Проверить сессии\n"
                  " [blue]3[/] — Показать метрики\n"
                  " [blue]4[/] — Купить аккаунты\n"
                  " [blue]5[/] — Синхронизировать купленные\n"
                  " [blue]0[/] — Выход")

    choice = typer.prompt("Номер", type=int)
    if choice == 1:
        mode = typer.prompt("Режим (slow/fast)", default="slow")
        ctx.invoke(send, mode=mode)
    elif choice == 2:
        ctx.invoke(check_sessions)
    elif choice == 3:
        ctx.invoke(dashboard)
    elif choice == 4:
        # Покупка аккаунтов через LolzMarket API
        count = typer.prompt("Сколько аккаунтов купить?", type=int)
        # Вызываем команду accounts buy
        ctx.invoke(accounts_buy, count=count)
        # Помещаем полученные .session-файлы в папку sessions и проверяем авторизацию
        console.print("\n[bold cyan]Помещаем полученные файлы сессий в папку sessions и проверяем их авторизацию...[/]")
        ctx.invoke(check_sessions)
    elif choice == 5:
        ctx.invoke(accounts_sync)
    else:
        console.print("Выход.")


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    app()