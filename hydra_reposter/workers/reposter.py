# hydra_reposter/workers/reposter.py
"""
Implements adaptive retry with exponential backoff (Tenacity) and human‑like
delays between message forwards to reduce anti‑spam triggers.
"""
from __future__ import annotations

import asyncio
import itertools
from pathlib import Path
from typing import List, Optional, Any

from telethon.errors import UserAlreadyParticipantError, RPCError, FloodError
from telethon.tl.functions.messages import ImportChatInviteRequest
import re
from typer.models import OptionInfo  # type: ignore

from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TimeElapsedColumn,
)
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    wait_exponential_jitter,
    stop_after_attempt,
)

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
from hydra_reposter.workers.login_worker import run_login_for_all
from hydra_reposter.core.proxy_service import ProxyManager

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
    *,
    dry_run: bool = False,
) -> bool:
    """
    Forward *msg_ids* from *donor* to every *target* (or just simulate if *dry_run*).
    Возвращает False, если сессия должна быть исключена (бан / карантин).
    """
    try:
        INV_RE = re.compile(r"(?:https?://)?t\.me/\+([a-zA-Z0-9_-]+)")
        donor_entity = None  # default – we fall back to the raw link if resolution fails

        if donor and (m := INV_RE.match(donor)):
            # «joinchat»‑style invite link.  First try to join the chat, then
            # resolve its entity *once* – this avoids a second API call that
            # may trigger FROZEN_METHOD_INVALID on some accounts.
            try:
                invite = await client(ImportChatInviteRequest(m.group(1)))
                # If join succeeded we can resolve the freshly‑joined chat
                if getattr(invite, "chats", None):
                    donor_entity = await client.get_input_entity(invite.chats[0])
            except UserAlreadyParticipantError:
                # Already a member – safe to resolve entity directly
                donor_entity = await client.get_input_entity(donor)
            except (RPCError, FloodError):
                # Method frozen or any other RPC error – skip entity resolution
                # `forward_messages` can work with the raw invite link.
                donor_entity = None
        else:
            donor_entity = await client.get_input_entity(donor) if donor else None

        for target in targets:
            # --------------------------------------------------------------
            # Robust resolution of the *target* to an InputPeer:
            #  • numeric id   -> int -> get_input_entity()
            #  • username     -> str  -> get_input_entity()
            #  • already‑resolved InputPeer is used as‑is
            # --------------------------------------------------------------
            try:
                if isinstance(target, int):  # already an int id
                    target_entity = await client.get_input_entity(target)
                elif isinstance(target, str):
                    cleaned = target.strip()
                    if cleaned.startswith("@"):
                        cleaned = cleaned[1:]          # drop leading '@'
                    if cleaned.isdigit():
                        target_entity = await client.get_input_entity(int(cleaned))
                    else:
                        target_entity = await client.get_input_entity(cleaned)
                else:
                    # Assume it's already an InputPeer‑like object
                    target_entity = target
            except (ValueError, RPCError) as ex:
                logger.warning("Cannot resolve target %s – skipping (%s)", target, ex)
                inc_metric("skipped")
                continue
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type(
                    (
                        FloodWaitBase,
                        ConnectionError,
                        OSError,
                        asyncio.TimeoutError,
                        socket.error,
                    )
                ),
                wait=wait_exponential_jitter(initial=2, max=90),
                stop=stop_after_attempt(5),
                reraise=True,
            ):
                with attempt:
                    # -- dry‑run mode: only count metrics and pretend success --
                    if dry_run:
                        logger.debug(
                            "[DRY‑RUN] %s -> %s : %s",
                            donor or "me",
                            target,
                            ",".join(map(str, msg_ids)),
                        )
                        inc_metric("sent_dry_run")
                        break

                    await client.forward_messages(
                        entity=target_entity,
                        messages=msg_ids,
                        from_peer=donor_entity or donor,
                    )
                    inc_metric("sent")
            # adaptive human‑delay: 2‑5 sec baseline, jitter helps desync calls
            await async_sleep_human(base=2, jitter=3)

    except FloodWaitBase as e:
        inc_metric("skipped")
        await asyncio.sleep(e.wait_seconds + 5)
        return True  # сессия ещё валидна
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
#   One‑time join of the donor chat for all sessions (sequential, proxy‑safe)
# --------------------------------------------------------------------------- #
async def _ensure_join_all(sessions: List[Path], donor: Optional[str], pm: ProxyManager) -> None:
    """
    Iterate over every *.session*, borrow a proxy from *pm*, open a short‑lived
    TelegramClient and try to join the donor chat exactly once.  Proxy is
    released right after each join so that only one account is ever connected
    through a specific proxy at a time.
    """
    if not donor:
        return

    INV_RE = re.compile(r"(?:https?://)?t\.me/\+([a-zA-Z0-9_-]+)")
    m = INV_RE.match(donor)
    invite_hash: str | None = m.group(1) if m else None
    username: str | None = None if invite_hash else donor.split("/")[-1].lstrip("@")

    for sess in sessions:
        proxy_cfg = await pm.acquire()
        try:
            async with telegram_client(sess, proxy=proxy_cfg) as cli:
                try:
                    if invite_hash:
                        await cli(ImportChatInviteRequest(invite_hash))
                    elif username:
                        from telethon.tl.functions.channels import JoinChannelRequest
                        await cli(JoinChannelRequest(username))
                except UserAlreadyParticipantError:
                    # already inside – nothing to do
                    pass
                except (RPCError, FloodError) as ex:
                    logger.warning("Failed pre‑join for %s: %s", sess.stem, ex)
        finally:
            await pm.release(proxy_cfg)

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
    """
    """
    # single ProxyManager instance for the whole slow‑mode loop
    pm = ProxyManager()
    # --- make sure every account has joined donor chat *once* ---
    await _ensure_join_all(sessions, donor, pm)
    cycle_sessions = itertools.cycle(sessions)

    # --- sticky proxy → session mapping ---
    proxy_map: dict[Path, tuple] = {}
    # keep one live TelegramClient per session to avoid repeated
    # open/close that locks the SQLite DB
    live_clients: dict[Path, TelegramClient] = {}
    live_cm: dict[Path, Any] = {}

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
                proxy_cfg = await pm.acquire()
                proxy_map[sess] = proxy_cfg

            # update progress‑bar fields with current account and proxy host
            prog.update(task, acc=sess.stem, ip=proxy_cfg[1] if proxy_cfg else "local")

            client = live_clients.get(sess)
            if client is None:
                client_cm = telegram_client(sess, proxy=proxy_cfg)
                client = await client_cm.__aenter__()
                live_clients[sess] = client
                live_cm[sess] = client_cm

            ok = await _handle_client(
                client, sess, donor, [tgt], msg_ids, dry_run=dry_run
            )

            if not ok:
                # close and forget the client tied to this broken session
                cm_to_close = live_cm.pop(sess, None)
                if cm_to_close:
                    await cm_to_close.__aexit__(None, None, None)
                live_clients.pop(sess, None)
                # release proxy assigned to the failing session
                await pm.release(proxy_map.pop(sess, None))
                sessions.remove(sess)
                if not sessions:  # все выбиты → ошибка или break
                    raise RuntimeError("Все сессии выбиты")
                cycle_sessions = itertools.cycle(sessions)  # пересобираем И ДО continue
                continue  # переносим сюда

            prog.update(task, advance=1)

        # cleanup: release any proxies that are still allocated
        for _sess, _px in proxy_map.items():
            await pm.release(_px)

        # close all still‑open Telegram clients
        for cm in live_cm.values():
            await cm.__aexit__(None, None, None)

        # update quarantine metric (import lazily to avoid cycles, but stay resilient
        # if the symbol is missing in older versions)
        try:
            from hydra_reposter.utils.quarantine import quarantine_size  # type: ignore
        except (ImportError, AttributeError):
            logger.warning(
                "utils.quarantine.quarantine_size not found – defaulting metric to 0"
            )

            def quarantine_size() -> int:  # fallback stub
                return 0

        set_gauge("quarantine_size", quarantine_size())

    # close ProxyManager and underlying httpx client(s)
    await pm.aclose()


# --------------------------------------------------------------------------- #
#   FAST MODE — заглушка
# --------------------------------------------------------------------------- #
async def _send_fast(clients, donor, targets, msg_ids, *, dry_run: bool = False):
    sem = asyncio.Semaphore(min(len(clients), 5))

    async def worker(client):
        async with sem:
            await _handle_client(
                client,
                Path(client.session.filename),
                donor,
                targets,
                msg_ids,
                dry_run=dry_run,
            )

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
    # --- CLI defensive sanitisation ------------------------------------
    # When invoked through `typer` with missing CLI flags, we might receive
    # bare `OptionInfo` placeholders instead of real data; normalise them.
    if isinstance(donor, OptionInfo):
        donor = None  # default to "forward from self"
    if isinstance(msg_ids, OptionInfo):
        msg_ids = None
    mode = (mode or "slow").strip().lower()
    if mode not in ("slow", "fast"):
        logger.warning(
            "Неизвестный режим %r – принудительно переключаюсь в 'slow'", mode
        )
        mode = "slow"

    # start metrics HTTP endpoint (idempotent – safe on repeated calls)
    start_metrics()
    targets = load_targets_from_csv(csv_path)

    async def _prepare() -> tuple[list[TelegramClient], list[Path]]:
        # collect every non‑quarantined session; no pre‑login here
        session_paths = [
            p for p in sessions_dir.glob("*.session") if not is_quarantined(p)
        ]
        return [], session_paths

    clients, session_paths = asyncio.run(_prepare())
    set_gauge("active_sessions", len(session_paths))
    if mode == "slow" and clients:
        for _c in clients:
            try:
                asyncio.run(_c.disconnect())
            except Exception as ex:  # pragma: no cover
                logger.debug("disconnect failed for %s: %s", _c.session.filename, ex)
            finally:
                try:
                    _c.session.close()
                except Exception as ex:
                    logger.debug("session.close() failed for %s: %s", _c.session.filename, ex)
    if mode == "slow" and not session_paths:
        logger.error("Нет ни одного авторизованного клиента")
        return
    if mode == "fast" and not clients:
        logger.error("Нет ни одного авторизованного клиента")
        return

    msg_ids = msg_ids or [1]  # временно один ID

    if mode == "slow":
        asyncio.run(_send_slow(session_paths, donor, targets, msg_ids, dry_run=dry_run))
    elif mode == "fast":
        asyncio.run(_send_fast(clients, donor, targets, msg_ids, dry_run=dry_run))
