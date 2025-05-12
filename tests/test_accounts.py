import pytest
import respx
from httpx import Response

from hydra_reposter.core.accounts_service import LolzMarketClient, LolzApiError
from hydra_reposter.cli import find_item
from hydra_reposter.core.config import settings

BASE = LolzMarketClient.BASE_URL

@pytest.mark.asyncio
@respx.mock
async def test_find_item_returns_none_when_no_items():
    # Mock empty items list
    route = respx.get(f"{BASE}/telegram").mock(
        return_value=Response(200, json={"items": []})
    )
    result = await find_item(int(settings.market_price * 100))
    assert result is None
    assert route.called

@pytest.mark.asyncio
@respx.mock
async def test_find_item_returns_item_id_and_price():
    # Mock single item response
    data = {"items": [{"item_id": 123, "price": 0.25}]}
    route = respx.get(f"{BASE}/telegram").mock(
        return_value=Response(200, json=data)
    )
    result = await find_item(int(settings.market_price * 100))
    assert result == (123, 0.25)
    assert route.called

@pytest.mark.asyncio
@respx.mock
async def test_fast_buy_success_and_return_item_structure():
    # Test fast_buy returns expected "item" structure on success
    payload = {"status": "ok", "item": {"item_id": 123, "price": 0.25}}
    route = respx.post(f"{BASE}/123/fast-buy").mock(
        return_value=Response(200, json=payload)
    )
    async with LolzMarketClient() as client:
        data = await client.fast_buy(item_id=123, price=0.25)
    assert "item" in data and data["item"]["item_id"] == 123 and data["item"]["price"] == 0.25
    assert route.called

@pytest.mark.asyncio
@respx.mock
async def test_fast_buy_raises_LolzApiError_on_http_error():
    # Test fast_buy raises exception on HTTP error
    route = respx.post(f"{BASE}/123/fast-buy").mock(
        return_value=Response(403, json={"errors": ["forbidden"]})
    )
    async with LolzMarketClient() as client:
        with pytest.raises(LolzApiError):
            await client.fast_buy(item_id=123, price=0.5)
    assert route.called

@pytest.mark.asyncio
@respx.mock
async def test_confirm_buy_and_get_code_and_reset_auth():
    # confirm_buy should raise on error
    route_confirm = respx.post(f"{BASE}/confirm-buy").mock(
        return_value=Response(400, json={"error": "bad lock"})
    )
    async with LolzMarketClient() as client:
        with pytest.raises(LolzApiError):
            await client.confirm_buy(999)
    assert route_confirm.called

    # get_code returns None
    route_code = respx.get(f"{BASE}/789/telegram-login-code").mock(
        return_value=Response(200, json={"code": None})
    )
    async with LolzMarketClient() as client:
        code = await client.get_code(789)
    assert code is None
    assert route_code.called

    # reset_auth returns True
    route_reset = respx.post(f"{BASE}/789/telegram-reset-auth").mock(
        return_value=Response(200, json={"success": True})
    )
    async with LolzMarketClient() as client:
        ok = await client.reset_auth(789)
    assert ok is True
    assert route_reset.called