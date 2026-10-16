import json
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any
from unittest.mock import Mock

import aiohttp
import pytest

from app.clients.deribit import DeribitClient, DeribitClientError
from app.core.tickers import Ticker


class FakeResponse:
    def __init__(
        self, status: int, payload: Any, *, raw_body: str | None = None
    ) -> None:
        self.status = status
        self._body = json.dumps(payload) if raw_body is None else raw_body

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def json(self, *, loads: Callable[[str], Any] = json.loads) -> Any:
        return loads(self._body)


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self._response = response
        self.request_url: str | None = None
        self.request_params: Mapping[str, str] | None = None

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str],
        timeout: object,
    ) -> FakeResponse:
        self.request_url = url
        self.request_params = params
        return self._response


@pytest.mark.asyncio
async def test_deribit_client_parses_valid_response() -> None:
    session = FakeSession(
        FakeResponse(200, {"jsonrpc": "2.0", "result": {"index_price": 67890.12}})
    )
    client = DeribitClient(
        "https://www.deribit.com/api/v2/",
        session=session,  # type: ignore[arg-type]
    )

    async with client:
        price = await client.get_index_price(Ticker.BTC_USD)

    assert price == Decimal("67890.12")
    assert session.request_url == (
        "https://www.deribit.com/api/v2/public/get_index_price"
    )
    assert session.request_params == {"index_name": "btc_usd"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "payload"),
    [
        (500, {"error": {"message": "internal_error"}}),
        (200, {"jsonrpc": "2.0", "result": {}}),
        (200, {"jsonrpc": "2.0", "result": {"index_price": "invalid"}}),
        (200, []),
        (200, {"result": []}),
        (200, {"error": {"code": 10000}, "result": {"index_price": 1}}),
        *[
            (200, {"result": {"index_price": price}})
            for price in (
                None,
                True,
                False,
                0,
                -1,
                "NaN",
                "Infinity",
                "-Infinity",
                [],
                {},
            )
        ],
    ],
)
async def test_deribit_client_rejects_error_or_invalid_response(
    status: int,
    payload: Any,
) -> None:
    session = FakeSession(FakeResponse(status, payload))
    client = DeribitClient(
        "https://www.deribit.com/api/v2",
        session=session,  # type: ignore[arg-type]
    )

    async with client:
        with pytest.raises(DeribitClientError):
            await client.get_index_price(Ticker.ETH_USD)


@pytest.mark.asyncio
async def test_json_numbers_do_not_pass_through_float() -> None:
    session = FakeSession(
        FakeResponse(
            200, None, raw_body='{"result":{"index_price":123456789.1234567891}}'
        )
    )
    async with DeribitClient("https://example.test", session=session) as client:  # type: ignore[arg-type]
        assert await client.get_index_price(Ticker.BTC_USD) == Decimal(
            "123456789.1234567891"
        )


@pytest.mark.asyncio
async def test_invalid_json_is_wrapped() -> None:
    session = FakeSession(FakeResponse(200, None, raw_body="{"))
    async with DeribitClient("https://example.test", session=session) as client:  # type: ignore[arg-type]
        with pytest.raises(DeribitClientError):
            await client.get_index_price(Ticker.BTC_USD)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [TimeoutError(), aiohttp.ClientConnectionError()])
async def test_network_errors_are_wrapped(error: Exception) -> None:
    session = Mock()
    session.get.side_effect = error
    async with DeribitClient("https://example.test", session=session) as client:
        with pytest.raises(DeribitClientError) as caught:
            await client.get_index_price(Ticker.BTC_USD)
    assert caught.value.__cause__ is error


@pytest.mark.asyncio
async def test_owned_http_session_is_closed_on_error() -> None:
    client = DeribitClient("https://example.test")
    with pytest.raises(RuntimeError, match="test failure"):
        async with client:
            session = client._session
            assert session is not None and not session.closed
            raise RuntimeError("test failure")
    assert session.closed


@pytest.mark.asyncio
async def test_injected_http_session_remains_open() -> None:
    async with aiohttp.ClientSession() as session:
        async with DeribitClient("https://example.test", session=session):
            pass
        assert not session.closed


@pytest.mark.asyncio
async def test_client_requires_context_manager() -> None:
    with pytest.raises(RuntimeError, match="async context manager"):
        await DeribitClient("https://example.test").get_index_price(Ticker.BTC_USD)
