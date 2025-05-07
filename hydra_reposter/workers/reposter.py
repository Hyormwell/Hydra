# hydra_reposter/workers/reposter.py
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
from hydra_reposter.utils.quarantine import is_quarantined, add_quarantine
from hydra_reposter.utils.delays import async_sleep_human
from hydra_reposter.utils.sessions import load_live_clients, resolve_donor


# --------------------------------------------------------------------------- #
#   LOW-LEVEL: пересылка для одного аккаунта
# --------------------------------------------------------------------------- #
async def _handle_account(
    session: Path,
    donor: Optional[str],
    targets: List[str],
    msg_ids: List[int],
) -> bool:
    """
    Переслать сообщения *msg_ids* из *donor* в каждый *target*.
    Возвращает False, если сессия должна быть исключена (бан / карантин).
    """
    try:
        async with telegram_client(session) as client:
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
                    retry=retry_if_exception_type(FloodWaitBase),
                    wait=wait_exponential_jitter(initial=1, max=60),
                    stop=stop_after_attempt(3),
                    reraise=True,
                ):
                    with attempt:
                        await client.forward_messages(
                            entity=target,
                            messages=msg_ids,
                            from_peer=donor_entity or donor,
                        )
                        inc_metric("sent")
                await async_sleep_human()

    except FloodWaitBase as e:
        inc_metric("skipped")
        await asyncio.sleep(e.wait_seconds + 5)
        return True                      # сессия ещё валидна
    except PeerFlood:
        inc_metric("peer_flood")
        add_quarantine(session, reason="PeerFlood")
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
) -> None:
    cycle_sessions = itertools.cycle(sessions)
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        transient=True,
    ) as prog:
        task = prog.add_task("Slow-mode", total=len(targets))
        for tgt in targets:
            if not sessions:
                raise RuntimeError("Нет активных сессий")

            sess = next(cycle_sessions)
            ok = await _handle_account(sess, donor, [tgt], msg_ids)

            if not ok:
                sessions.remove(sess)
                if not sessions:  # все выбиты → ошибка или break
                    raise RuntimeError("Все сессии выбиты")
                cycle_sessions = itertools.cycle(sessions)  # пересобираем И ДО continue
                continue  # переносим сюда

            prog.update(task, advance=1)


# --------------------------------------------------------------------------- #
#   FAST MODE — Semaphore + gather
# --------------------------------------------------------------------------- #
async def _send_fast(
    sessions: List[Path],
    donor: Optional[str],
    targets: List[str],
    msg_ids: List[int],
) -> None:
    sem = asyncio.Semaphore(min(len(sessions), 5))

    async def worker(sess: Path, tgt: str):
        async with sem:
            await _handle_account(sess, donor, [tgt], msg_ids)

    tasks = [worker(s, t) for s, t in itertools.product(sessions, targets)]
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        transient=True,
    ) as prog:
        task = prog.add_task("Fast-mode", total=len(tasks))
        for coro in asyncio.as_completed(tasks):
            await coro
            prog.update(task, advance=1)


# --------------------------------------------------------------------------- #
#   PUBLIC API — вызывается CLI
# --------------------------------------------------------------------------- #
def run_reposter(
    csv_path: Path,
    donor: Optional[str],
    sessions_dir: Path,
    mode: str = "slow",
    msg_ids: Optional[List[int]] = None,
) -> None:
    targets = load_targets_from_csv(csv_path)
    sessions = [p for p in sessions_dir.glob("*.session") if not is_quarantined(p)]
    live_clients = asyncio.run(load_live_clients(sessions_dir))
    sessions = [Path(c.session.filename) for c in live_clients]
    if not sessions:
        raise RuntimeError("Нет живых сессий")
    msg_ids = msg_ids or [1]            # временно один ID

    if mode == "fast":
        asyncio.run(_send_fast(sessions, donor, targets, msg_ids))
    else:
        asyncio.run(_send_slow(sessions, donor, targets, msg_ids))