from __future__ import annotations
import os
import json
import logging
from pathlib import Path
from typing import Optional, Tuple

import backoff
import httpx

from hydra_reposter.core.config import settings

logger = logging.getLogger(__name__)
ProxyTuple = Tuple[
    str, str, int, bool, Optional[str], Optional[str]
]  # scheme,host,port,rdns,user,pwd
BLACKLIST = Path("blacklist.json")


class ProxyError(Exception): ...


# --------------------------------------------------------------------- #
#                               Back-off                               #
# --------------------------------------------------------------------- #
def _log_backoff(details):
    logger.warning("ProxyAPI failed — retrying (%d tries)", details["tries"])


retry_on_5xx = backoff.on_exception(
    backoff.expo,
    httpx.HTTPStatusError,
    max_time=30,
    on_backoff=_log_backoff,
)


# --------------------------------------------------------------------- #
#                             AnyIP backend                             #
# --------------------------------------------------------------------- #
class AnyIPBackend:
    """Back-connect gateway: IP меняется при каждом TCP-коннекте."""

    def __init__(self):
        self.user = settings.anyip_username
        self.pwd = settings.anyip_password
        self.host = settings.anyip_proxy_host
        self.port = settings.anyip_proxy_port

    async def acquire(self) -> ProxyTuple:
        return ("socks5", self.host, self.port, True, self.user, self.pwd)

    async def rotate(self) -> bool:
        # смена IP происходит автоматически; отдельного энд-пойнта нет
        return True

    async def blacklist(self) -> bool:
        _add_to_blacklist(self.user)
        return True


# --------------------------------------------------------------------- #
#                           Proxy-Seller backend                        #
# --------------------------------------------------------------------- #
class ProxySellerBackend:
    BASE_URL: str = "https://proxy-seller.com"
    API_PREFIX: str = "/personal/api/v1"
    BASE: str = BASE_URL + API_PREFIX

    def __init__(self):
        self.token = os.getenv("PROXYSELLER_TOKEN")
        self.proxy_id = os.getenv("PROXYSELLER_ID")
        # Use BASE exactly as base_url (no trailing slash) so tests can mock correctly
        self._client = httpx.AsyncClient(
            base_url=self.BASE,
            timeout=10.0,
            limits=httpx.Limits(max_connections=10),
        )

    @retry_on_5xx
    async def acquire(self) -> ProxyTuple:
        # include token in path for API calls
        r = await self._client.get(f"/{self.token}/proxy/info/{self.proxy_id}")
        r.raise_for_status()
        data = r.json()
        host, port = data["ip"], int(data["port"])
        user, pwd = data["userLogin"], data["userPassword"]
        return ("socks5", host, port, True, user, pwd)

    @retry_on_5xx
    async def rotate(self) -> bool:
        # include token in path for API calls
        r = await self._client.post(
            f"/{self.token}/proxy/change-ip",
            json={"proxyId": self.proxy_id},
        )
        r.raise_for_status()
        return bool(r.json().get("success"))

    async def blacklist(self) -> bool:
        _add_to_blacklist(str(self.proxy_id))
        return True

    async def aclose(self):
        await self._client.aclose()


# --------------------------------------------------------------------- #
#                              ProxyManager                             #
# --------------------------------------------------------------------- #
class ProxyManager:
    def __init__(self):
        provider = os.getenv("PROXY_PROVIDER", "anyip").lower()
        if provider == "anyip":
            self.backend = AnyIPBackend()
        elif provider == "proxyseller":
            self.backend = ProxySellerBackend()
        else:
            raise ValueError(f"Unknown proxy provider: {provider}")

    async def acquire(self) -> ProxyTuple:
        proxy = await self.backend.acquire()
        if _is_blacklisted(proxy[1]):
            raise ProxyError("Proxy is blacklisted")
        return proxy

    async def rotate(self) -> bool:
        return await self.backend.rotate()

    async def blacklist(self) -> bool:
        return await self.backend.blacklist()

    async def release(self, proxy: ProxyTuple) -> bool:
        """
        Placeholder method to maintain interface compatibility.
        Currently it just returns True, but it can be expanded later
        to recycle or close proxy connections if needed.

        :param proxy: The proxy tuple that should be released back to the pool.
        :return: True on success.
        """
        # For now, no-op. Implement provider‑specific cleanup here if required.
        return True

    async def aclose(self):
        if hasattr(self.backend, "aclose"):
            await self.backend.aclose()


# --------------------------------------------------------------------- #
#                          Black-list helpers                           #
# --------------------------------------------------------------------- #
def _load_bl() -> set[str]:
    if not BLACKLIST.exists():
        return set()
    return set(json.loads(BLACKLIST.read_text()))


def _save_bl(data: set[str]):
    BLACKLIST.write_text(json.dumps(sorted(data)))


def _add_to_blacklist(identifier: str):
    data = _load_bl()
    data.add(identifier)
    _save_bl(data)


def _is_blacklisted(identifier: str) -> bool:
    return identifier in _load_bl()
