from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import pytest

from app.clients.deribit import DeribitClient, DeribitClientError
from app.core.tickers import Ticker


class FakeResponse:
    def __init__(self, status: int, payload: Any) -> None:
        self.status = status
        self._payload = payload

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def json(self) -> Any:
        return self._payload


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
