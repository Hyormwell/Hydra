# tests/test_proxy_manager.py
import pytest, respx, httpx, asyncio
from hydra_reposter.core.proxy_service import ProxyManager, AnyIPBackend, ProxySellerBackend

@pytest.mark.asyncio
async def test_anyip_acquire():
    pm = ProxyManager()     # provider anyip
    scheme, host, port, rdns, user, pwd = await pm.acquire()
    assert scheme == "socks5" and host and port

@pytest.mark.asyncio
async def test_proxyseller_rotate(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXY_PROVIDER", "proxyseller")
    monkeypatch.setenv("PROXYSELLER_TOKEN", "t")
    monkeypatch.setenv("PROXYSELLER_ID", "42")

    with respx.mock(base_url="https://proxy-seller.com") as mock:
        mock.get("/personal/api/v1/t/proxy/info/42").respond(
            json={"ip": "1.1.1.1", "port": 1080, "userLogin": "u", "userPassword": "p"}
        )
        mock.post("/personal/api/v1/t/proxy/change-ip").respond(json={"success": True})
        pm = ProxyManager()
        await pm.acquire()
        ok = await pm.rotate()
        assert ok is True