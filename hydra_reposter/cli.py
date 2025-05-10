"""
Hydra Reposter CLI
~~~~~~~~~~~~~~~~~~
Typer-приложение с баннером а-ля TGSpammer и интерактивным меню.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional, List

from hydra_reposter.core.accounts_service import LolzMarketClient, LolzApiError
from hydra_reposter.core.proxy_service import ProxyManager, ProxyError

import typer
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

app = typer.Typer(add_completion=False, help="Hydra Reposter — модульная пересылка сообщений в Telegram")
console = Console()


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
        csv_file: Path = typer.Option("data/targets.csv", "--csv", "-c"),
        donor: Optional[str] = typer.Option("https://t.me/+AtkcqZPW5kM1Y2Jl", "--donor", "-d"),
        mode: str = typer.Option("slow", "--mode", "-m"),
        ids: List[int] = typer.Option([1], "--id", help="ID сообщений"),
):
    """Команда: старт пересылки"""
    console.print(Spinner("dots", text="Загружаю CSV…"), end="\r")
    targets = [int(t) if str(t).isdigit() else t for t in load_targets_from_csv(csv_file)]
    console.print(f"[bold cyan]Целей:[/] {len(targets)}")

    #Проверяем какие сессии активны
    sessions_dir = Path(settings.sessions_dir)  # ← есть в config

    sessions = [p for p in sessions_dir.glob("*.session") if not is_quarantined(p)]
    dead = len([p for p in sessions_dir.glob("*.session")]) - len(sessions)
    if dead:
        console.print(f"[yellow]Пропущено сессий (карантин/не авторизованы): {dead}[/]")

    # Запуск репостера
    run_reposter(csv_file, donor, sessions_dir, mode, ids)

    console.print("\n[bold green]Готово![/]")
    console.print(f"Отправлено: {get_metric('sent')}, пропущено: {get_metric('skipped')}")


@app.command("check-sessions", help="Проверить авторизацию всех .session")
def check_sessions():
    sessions = Path(settings.sessions_dir).glob("*.session")
    ok, bad = 0, 0
    for s in sessions:
        try:
            # быстрая проверка через context manager
            from hydra_reposter.core.client import telegram_client

            asyncio.run(telegram_client(s).__aenter__())
            console.print(f"[green]OK[/] {s.name}")
            ok += 1
        except Exception as e:
            console.print(f"[red]FAIL[/] {s.name} — {e}")
            bad += 1
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
        async with LolzMarketClient() as client:
            success = 0
            for _ in range(count):
                try:
                    res = await client.fast_buy(item_id=settings.market_item_id, price=settings.market_price)
                    console.print(f"[green]Куплен аккаунт:[/] lock_id={res['lock_id']}, item_id={res['item_id']}")
                    success += 1
                except LolzApiError as e:
                    console.print(f"[red]Ошибка покупки:[/] {e}")
            console.print(f"\n[bold green]Успешно куплено {success} из {count}[/]")
    asyncio.run(_buy())

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
    print_banner()
    if ctx.invoked_subcommand:
        return

    console.print("[bold]Выберите действие:[/]\n"
                  " [blue]1[/] — Запустить рассылку\n"
                  " [blue]2[/] — Проверить сессии\n"
                  " [blue]3[/] — Показать метрики\n"
                  " [blue]4[/] — Купить аккаунты\n"
                  " [blue]0[/] — Выход")

    choice = typer.prompt("Номер", type=int)
    if choice == 1:
        csv_path = Path(typer.prompt("CSV-файл"))
        donor = typer.prompt("Донор (@… или ID)", default="")
        mode = typer.prompt("Режим (slow/fast)", default="slow")
        ctx.invoke(send, csv_file=csv_path, donor=donor or None, mode=mode)
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
    else:
        console.print("Выход.")


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    app()