import asyncio
from collections.abc import Iterator
from decimal import Decimal
from types import ModuleType
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clients.deribit import DeribitClientError
from app.core.config import get_settings
from app.core.tickers import Ticker
from app.db.models.price import PriceRecord
from app.db.repositories.price import PriceRepository


@pytest.fixture
def collection_module(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite://")
    monkeypatch.setenv("REDIS_URL", "redis://localhost/0")
    get_settings.cache_clear()
    from app.tasks import prices

    try:
        yield prices
    finally:
        get_settings.cache_clear()


@pytest.fixture
def collection_dependencies(
    collection_module: ModuleType,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Mock, Mock]:
    engine = Mock(dispose=AsyncMock())
    client = Mock(
        get_index_price=AsyncMock(side_effect=[Decimal("123.45"), Decimal("67.89")])
    )
    context = AsyncMock()
    context.__aenter__.return_value = client
    monkeypatch.setattr(collection_module, "create_engine", lambda url: engine)
    monkeypatch.setattr(
        collection_module, "create_session_factory", lambda value: session_factory
    )
    monkeypatch.setattr(collection_module, "DeribitClient", lambda **kwargs: context)
    monkeypatch.setattr(collection_module.time, "time", lambda: 1_791_936_000)
    return engine, client


@pytest.mark.asyncio
async def test_collection_persists_both_tickers(
    collection_module: ModuleType,
    collection_dependencies: tuple[Mock, Mock],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await collection_module._collect_index_prices()
    engine, client = collection_dependencies
    assert client.get_index_price.await_args_list[0].args == (Ticker.BTC_USD,)
    assert client.get_index_price.await_args_list[1].args == (Ticker.ETH_USD,)
    async with session_factory() as session:
        for ticker, price in [(Ticker.BTC_USD, "123.45"), (Ticker.ETH_USD, "67.89")]:
            record = await PriceRepository(session).get_latest(ticker)
            assert record is not None
            assert record.price == Decimal(price)
            assert record.timestamp == 1_791_936_000
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        DeribitClientError("offline"),
        TimeoutError("deadline"),
        ConnectionRefusedError("offline"),
    ],
)
async def test_collection_continues_after_fetch_failure_and_reports_failure(
    collection_module: ModuleType,
    collection_dependencies: tuple[Mock, Mock],
    session_factory: async_sessionmaker[AsyncSession],
    error: Exception,
) -> None:
    engine, client = collection_dependencies
    client.get_index_price.side_effect = [error, Decimal("67.89")]
    with pytest.raises(ExceptionGroup) as caught:
        await collection_module._collect_index_prices()
    assert caught.value.exceptions == (error,)
    async with session_factory() as session:
        repository = PriceRepository(session)
        assert await repository.get_latest(Ticker.BTC_USD) is None
        assert await repository.get_latest(Ticker.ETH_USD) is not None
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_collection_continues_after_database_failure(
    collection_module: ModuleType,
    collection_dependencies: tuple[Mock, Mock],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_add = PriceRepository.add

    async def fail_btc(
        self: PriceRepository, ticker: Ticker, price: Decimal, timestamp: int
    ) -> PriceRecord:
        if ticker == Ticker.BTC_USD:
            raise SQLAlchemyError("database failed")
        return await original_add(self, ticker, price, timestamp)

    monkeypatch.setattr(PriceRepository, "add", fail_btc)
    with pytest.raises(ExceptionGroup):
        await collection_module._collect_index_prices()
    async with session_factory() as session:
        assert await PriceRepository(session).get_latest(Ticker.ETH_USD) is not None
    collection_dependencies[0].dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_unexpected_failure_is_not_swallowed_and_disposes_engine(
    collection_module: ModuleType,
    collection_dependencies: tuple[Mock, Mock],
) -> None:
    engine, client = collection_dependencies
    client.get_index_price.side_effect = RuntimeError("programming error")
    with pytest.raises(RuntimeError, match="programming error"):
        await collection_module._collect_index_prices()
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_both_fetch_failures_are_reported(
    collection_module: ModuleType,
    collection_dependencies: tuple[Mock, Mock],
) -> None:
    engine, client = collection_dependencies
    errors = [
        DeribitClientError("BTC unavailable"),
        DeribitClientError("ETH unavailable"),
    ]
    client.get_index_price.side_effect = errors
    with pytest.raises(ExceptionGroup) as caught:
        await collection_module._collect_index_prices()
    assert caught.value.exceptions == tuple(errors)
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_deadline_cancels_blocked_fetches_and_closes_resources(
    collection_module: ModuleType,
    collection_dependencies: tuple[Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, client = collection_dependencies

    async def blocked_fetch(ticker: Ticker) -> Decimal:
        await asyncio.Future()
        raise AssertionError("Cancelled fetch must not resume")

    client.get_index_price.side_effect = blocked_fetch
    original_timeout = asyncio.timeout
    deadline = Mock(side_effect=lambda seconds: original_timeout(0))
    monkeypatch.setattr(collection_module.asyncio, "timeout", deadline)
    with pytest.raises(ExceptionGroup) as caught:
        await collection_module._collect_index_prices()
    assert len(caught.value.exceptions) == 2
    assert all(isinstance(error, TimeoutError) for error in caught.value.exceptions)
    assert [call.args for call in deadline.call_args_list] == [(25,), (25,)]
    assert client.get_index_price.await_count == 2
    engine.dispose.assert_awaited_once()


def test_celery_wrapper_and_schedule(
    collection_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    collect = AsyncMock()
    monkeypatch.setattr(collection_module, "_collect_index_prices", collect)
    collection_module.collect_index_prices.run()
    collect.assert_awaited_once()
    schedule = collection_module.celery_app.conf.beat_schedule[
        "collect-index-prices-every-minute"
    ]
    assert schedule["task"] == collection_module.collect_index_prices.name
    assert schedule["schedule"] == 60.0
    assert schedule["options"]["expires"] == 60
    assert collection_module.collect_index_prices.soft_time_limit == 55
    assert collection_module.collect_index_prices.time_limit == 60
    assert collection_module.celery_app.conf.worker_prefetch_multiplier == 1
