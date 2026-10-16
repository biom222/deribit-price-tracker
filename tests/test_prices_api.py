from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.tickers import Ticker
from app.db.repositories.price import PriceRepository


async def add_price(
    session_factory: async_sessionmaker[AsyncSession],
    ticker: Ticker,
    price: str,
    timestamp: int,
) -> None:
    async with session_factory() as session:
        await PriceRepository(session).add(ticker, Decimal(price), timestamp)


@pytest.mark.asyncio
async def test_get_all_prices_returns_newest_first(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_price(session_factory, Ticker.BTC_USD, "62000.12", 1_760_400_000)
    await add_price(session_factory, Ticker.BTC_USD, "62500.34", 1_760_400_060)
    await add_price(session_factory, Ticker.ETH_USD, "4000.00", 1_760_400_070)

    response = await client.get("/api/v1/prices", params={"ticker": "btc_usd"})

    assert response.status_code == 200
    assert [item["price"] for item in response.json()] == [
        "62500.3400000000",
        "62000.1200000000",
    ]


@pytest.mark.asyncio
async def test_get_latest_price(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_price(session_factory, Ticker.ETH_USD, "4100.50", 1_760_400_000)
    await add_price(session_factory, Ticker.ETH_USD, "4200.75", 1_760_400_060)

    response = await client.get(
        "/api/v1/prices/latest",
        params={"ticker": "eth_usd"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "ticker": "eth_usd",
        "price": "4200.7500000000",
        "timestamp": 1_760_400_060,
    }


@pytest.mark.asyncio
async def test_get_latest_price_returns_404_when_empty(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/prices/latest",
        params={"ticker": "btc_usd"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "No prices found for btc_usd"}


@pytest.mark.asyncio
async def test_get_prices_by_utc_date(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # 2026-10-14 00:00:00 UTC, midday, and next midnight.
    await add_price(session_factory, Ticker.BTC_USD, "61000", 1_791_936_000)
    await add_price(session_factory, Ticker.BTC_USD, "62000", 1_791_979_200)
    await add_price(session_factory, Ticker.BTC_USD, "63000", 1_792_022_400)

    response = await client.get(
        "/api/v1/prices/by-date",
        params={"ticker": "btc_usd", "date": "2026-10-14"},
    )

    assert response.status_code == 200
    assert [item["timestamp"] for item in response.json()] == [
        1_791_979_200,
        1_791_936_000,
    ]


@pytest.mark.asyncio
async def test_unsupported_ticker_returns_validation_error(client: AsyncClient) -> None:
    response = await client.get("/api/v1/prices", params={"ticker": "sol_usd"})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_date_returns_validation_error(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/prices/by-date",
        params={"ticker": "btc_usd", "date": "14-10-2026"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ticker_is_required_for_every_price_endpoint(
    client: AsyncClient,
) -> None:
    responses = [
        await client.get("/api/v1/prices"),
        await client.get("/api/v1/prices/latest"),
        await client.get("/api/v1/prices/by-date", params={"date": "2026-10-14"}),
    ]

    assert all(response.status_code == 422 for response in responses)
