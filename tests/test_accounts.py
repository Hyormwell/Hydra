# tests/test_lolz_market_client.py
import pytest
import respx
import httpx

from hydra_reposter.core.accounts_service import LolzMarketClient, LolzApiError


@pytest.mark.asyncio
async def test_fast_buy_success():
    with respx.mock(base_url=LolzMarketClient.BASE_URL) as mock:
        route = mock.post("/123/fast-buy").respond(
            status_code=200,
            json={"lock_id": 555, "item_id": 123, "status": "locked"},
        )

        async with LolzMarketClient(token="dummy") as api:
            data = await api.fast_buy(123, 99.0)

        assert data["lock_id"] == 555
        assert route.called


@pytest.mark.asyncio
async def test_confirm_buy_error():
    with respx.mock(base_url=LolzMarketClient.BASE_URL) as mock:
        mock.post("/confirm-buy").respond(status_code=400, json={"error": "bad lock"})

        async with LolzMarketClient(token="dummy") as api:
            with pytest.raises(LolzApiError):
                await api.confirm_buy(999)


@pytest.mark.asyncio
async def test_get_code_none():
    with respx.mock(base_url=LolzMarketClient.BASE_URL) as mock:
        mock.get("/789/telegram-login-code").respond(status_code=200, json={"code": None})

        async with LolzMarketClient(token="dummy") as api:
            code = await api.get_code(789)

        assert code is None


@pytest.mark.asyncio
async def test_reset_auth_true():
    with respx.mock(base_url=LolzMarketClient.BASE_URL) as mock:
        mock.post("/789/telegram-reset-auth").respond(status_code=200, json={"success": True})

        async with LolzMarketClient(token="dummy") as api:
            ok = await api.reset_auth(789)

        assert ok is True