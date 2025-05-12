# hydra_reposter/workers/reposter.py
"""
Implements adaptive retry with exponential backoff (Tenacity) and human‑like
delays between message forwards to reduce anti‑spam triggers.
"""
from __future__ import annotations

import asyncio
import itertools
from pathlib import Path
from typing import List, Optional

from telethon.errors import UserAlreadyParticipantError
from telethon.tl.functions.messages import ImportChatInviteRequest
import re

from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from tenacity import AsyncRetrying, retry_if_exception_type, wait_exponential_jitter, stop_after_attempt

from hydra_reposter.core.client import telegram_client
from hydra_reposter.core.errors import (
    FloodWaitBase,
    PeerFlood,
    PrivacySkip,
    ChatWriteForbidden,
    AccountBanned,
    AuthRequired,
)
from hydra_reposter.utils.csv_loader import load_targets_from_csv
from hydra_reposter.utils.metrics import inc_metric
from hydra_reposter.utils.metrics import start_metrics, set_gauge
from hydra_reposter.utils.quarantine import is_quarantined, add_quarantine
from hydra_reposter.utils.delays import async_sleep_human
from hydra_reposter.utils.sessions import load_live_clients, resolve_donor
from hydra_reposter.workers.login_worker import run_login_for_all
from hydra_reposter.core.proxy_service import ProxyManager
from hydra_reposter.core import settings

from telethon import TelegramClient
from loguru import logger
import socket


# --------------------------------------------------------------------------- #
#   LOW-LEVEL: пересылка для одного аккаунта
# --------------------------------------------------------------------------- #
async def _handle_client(
        client: TelegramClient,
        session_path: Path,
        donor: Optional[str],
        targets: list[str],
        msg_ids: list[int],
) -> bool:
    """
    Переслать сообщения *msg_ids* из *donor* в каждый *target*.
    Возвращает False, если сессия должна быть исключена (бан / карантин).
    """
    try:
        INV_RE = re.compile(r"(?:https?://)?t\.me/\+([a-zA-Z0-9_-]+)")
        if donor and (m := INV_RE.match(donor)):
            try:
                await client(ImportChatInviteRequest(m.group(1)))
            except UserAlreadyParticipantError:
                pass  # уже вступили
            donor_entity = await client.get_input_entity(donor)
        else:
            donor_entity = await client.get_input_entity(donor) if donor else None

        for target in targets:
            for attempt in AsyncRetrying(
                retry=retry_if_exception_type(
                    (FloodWaitBase, ConnectionError, OSError, asyncio.TimeoutError, socket.error)
                ),
                wait=wait_exponential_jitter(initial=2, max=90),
                stop=stop_after_attempt(5),
                reraise=True,
            ):
                with attempt:
                    await client.forward_messages(
                        entity=target,
                        messages=msg_ids,
                        from_peer=donor_entity or donor,
                    )
                    inc_metric("sent")
            # adaptive human‑delay: 2‑5 sec baseline, jitter helps desync calls
            await async_sleep_human(base=2, jitter=3)

    except FloodWaitBase as e:
        inc_metric("skipped")
        await asyncio.sleep(e.wait_seconds + 5)
        return True                      # сессия ещё валидна
    except PeerFlood:
        inc_metric("peer_flood")
        add_quarantine(session_path, reason="PeerFlood")
        return False
    except (PrivacySkip, ChatWriteForbidden):
        inc_metric("skipped")
        return True
    except AccountBanned:
        inc_metric("skipped")
        return False
    except AuthRequired:
        return False
    return True

# --------------------------------------------------------------------------- #
#   SLOW MODE — round-robin
# --------------------------------------------------------------------------- #
async def _send_slow(
    sessions: List[Path],
    donor: Optional[str],
    targets: List[str],
    msg_ids: List[int],
    dry_run: bool = False,
) -> None:
    cycle_sessions = itertools.cycle(sessions)

    # --- sticky proxy → session mapping ---
    proxy_map: dict[Path, tuple] = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TextColumn("[bold blue]{task.fields[acc]}", justify="right"),
        TextColumn("[green]{task.fields[ip]}", justify="right"),
        BarColumn(),
        TimeElapsedColumn(),
        transient=True,
    ) as prog:
        task = prog.add_task(
            "Slow-mode",
            total=len(targets),
            acc="—",
            ip="—",
        )
        for tgt in targets:
            if not sessions:
                raise RuntimeError("Нет активных сессий")

            sess = next(cycle_sessions)
            # obtain (or reuse) a dedicated proxy for this session
            proxy_cfg = proxy_map.get(sess)
            if proxy_cfg is None:
                proxy_cfg = await ProxyManager.acquire()
                proxy_map[sess] = proxy_cfg

            # update progress‑bar fields with current account and proxy host
            prog.update(task, acc=sess.stem, ip=proxy_cfg[1] if proxy_cfg else "local")

            client_cm = telegram_client(sess, proxy=proxy_cfg)
            client = await client_cm.__aenter__()   # get live client with sticky proxy

            ok = await _handle_client(client, sess, donor, [tgt], msg_ids, dry_run=dry_run)
            await client_cm.__aexit__(None, None, None)

            if not ok:
                # release proxy assigned to the failing session
                await ProxyManager.release(proxy_map.pop(sess, None))
                sessions.remove(sess)
                if not sessions:  # все выбиты → ошибка или break
                    raise RuntimeError("Все сессии выбиты")
                cycle_sessions = itertools.cycle(sessions)  # пересобираем И ДО continue
                continue  # переносим сюда

            prog.update(task, advance=1)

        # cleanup: release any proxies that are still allocated
        for _sess, _px in proxy_map.items():
            await ProxyManager.release(_px)

        from hydra_reposter.utils.quarantine import quarantine_size  # lazy import to avoid cycle
        set_gauge("quarantine_size", quarantine_size())

# --------------------------------------------------------------------------- #
#   FAST MODE — заглушка
# --------------------------------------------------------------------------- #
async def _send_fast(clients, donor, targets, msg_ids):
    sem = asyncio.Semaphore(min(len(clients), 5))
    async def worker(client):
        async with sem:
            await _handle_client(client, Path(client.session.filename), donor, targets, msg_ids)
    await asyncio.gather(*(worker(c) for c in clients))
# --------------------------------------------------------------------------- #
#   PUBLIC API — вызывается CLI
# --------------------------------------------------------------------------- #
def run_reposter(
    csv_path: Path,
    donor: Optional[str],
    sessions_dir: Path,
    mode: str = "slow",
    msg_ids: Optional[List[int]] = None,
    dry_run: bool = False,
) -> None:
    # start metrics HTTP endpoint (idempotent – safe on repeated calls)
    start_metrics()
    targets = load_targets_from_csv(csv_path)

    async def _prepare() -> tuple[list[TelegramClient], list[Path]]:
        session_paths = [p for p in sessions_dir.glob("*.session") if not is_quarantined(p)]
        pm = ProxyManager()
        proxies = [await pm.acquire() for _ in session_paths]
        item_ids = [idx for idx, _ in enumerate(session_paths)]  # stub mapping
        # run_login_for_all performs its own event‑loop handling; execute it in a
        # separate thread to avoid "asyncio.run() cannot be called from a running loop"
        loop_in = asyncio.get_running_loop()
        clients = await loop_in.run_in_executor(
            None,
            lambda: run_login_for_all(session_paths, proxies=proxies, item_ids=item_ids),
        )
        await pm.aclose()
        return clients, session_paths

    clients, session_paths = asyncio.run(_prepare())
    set_gauge("active_sessions", len(clients))
    if not clients:
        logger.error("Нет ни одного авторизованного клиента")
        return

    msg_ids = msg_ids or [1]            # временно один ID

    if mode == "slow":
        asyncio.run(_send_slow(session_paths, donor, targets, msg_ids, dry_run=dry_run))
    elif mode == "fast":
        asyncio.run(_send_fast(clients, donor, targets, msg_ids, dry_run=dry_run))