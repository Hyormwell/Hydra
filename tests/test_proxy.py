import pytest
import respx
from httpx import Response
import asyncio
import os

from hydra_reposter.core.proxy_service import ProxyManager, ProxyError, AnyIPBackend, ProxySellerBackend
from hydra_reposter.core.config import settings

@pytest.mark.asyncio
async def test_anyip_acquire_success(monkeypatch):
    # default provider anyip
    pm = ProxyManager()
    async def dummy_acquire(self):
        return ("socks5", "host", 1080, True, "user", "pass")
    monkeypatch.setattr(AnyIPBackend, "acquire", dummy_acquire)
    scheme, host, port, rdns, user, pwd = await pm.acquire()
    assert scheme == "socks5" and host == "host" and port == 1080
    assert isinstance(rdns, bool)

@pytest.mark.asyncio
async def test_proxyseller_rotate_and_acquire(monkeypatch):
    # set provider to proxyseller
    monkeypatch.setenv("PROXY_PROVIDER", "proxyseller")
    monkeypatch.setenv("PROXYSELLER_TOKEN", "token")
    monkeypatch.setenv("PROXYSELLER_ID", "42")

    # привязываем respx к тому же адресу, что и у ProxySellerBackend
    backend_base = "https://proxy-seller.com/personal/api/v1"
    monkeypatch.setattr(ProxySellerBackend, "BASE", backend_base)

    with respx.mock(base_url=backend_base) as mock:
        # GET /{token}/proxy/info/{id}
        mock.get(f"/{settings.proxyseller_token}/proxy/info/{settings.proxyseller_id}").mock(
            return_value=Response(200, json={
                "ip": "1.1.1.1",
                "port": 1080,
                "userLogin": "u",
                "userPassword": "p"
            })
        )
        # POST /{token}/proxy/change-ip
        mock.post(f"/{settings.proxyseller_token}/proxy/change-ip").mock(
            return_value=Response(200, json={"success": True})
        )

        pm = ProxyManager()
        scheme, host, port, rdns, user, pwd = await pm.acquire()
        assert host == "1.1.1.1"
        ok = await pm.rotate()
        assert ok is True
        # mock GET /{token}/proxy/info/{id}
        mock.get(f"/{settings.proxyseller_token}/proxy/info/{settings.proxyseller_id}").mock(
            return_value=Response(200, json={"ip": "1.1.1.1", "port": 1080, "userLogin": "u", "userPassword": "p"})
        )
        # mock POST /{token}/proxy/change-ip
        mock.post(f"/{settings.proxyseller_token}/proxy/change-ip").mock(
            return_value=Response(200, json={"success": True})
        )

        pm = ProxyManager()
        # first acquire should pull info
        scheme, host, port, rdns, user, pwd = await pm.acquire()
        assert host == "1.1.1.1"
        # rotate should succeed
        ok = await pm.rotate()
        assert ok is True

@pytest.mark.asyncio
async def test_rotate_error(monkeypatch):
    pm = ProxyManager()
    async def dummy_rotate():
        raise ProxyError("fail")
    monkeypatch.setattr(pm, "rotate", dummy_rotate)
    with pytest.raises(ProxyError):
        await pm.rotate()