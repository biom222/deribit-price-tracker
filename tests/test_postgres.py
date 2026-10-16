import asyncio
import os
import subprocess
import sys
from decimal import Decimal

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.tickers import Ticker
from app.db.base import Base
from app.db.repositories.price import PriceRepository


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_migration_and_decimal_roundtrip() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "TEST_DATABASE_URL must point to a dedicated PostgreSQL test database"
        )
    environment = {
        **os.environ,
        "DATABASE_URL": database_url,
        "REDIS_URL": "redis://localhost/0",
    }
    await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            differences = await connection.run_sync(
                lambda sync_connection: compare_metadata(
                    MigrationContext.configure(
                        sync_connection, opts={"compare_type": True}
                    ),
                    Base.metadata,
                )
            )
            assert differences == []
            await connection.rollback()
            transaction = await connection.begin()
            try:
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    repository = PriceRepository(session)
                    price = Decimal("123456789.1234567891")
                    first = await repository.add(Ticker.BTC_USD, price, 4_000_000_000)
                    first_id = first.id
                    session.expunge_all()
                    saved = await repository.get_latest(Ticker.BTC_USD)
                    assert saved is not None and saved.id == first_id
                    assert saved.price == price
                    second = await repository.add(
                        Ticker.BTC_USD, Decimal("2"), 4_000_000_000
                    )
                    await repository.add(Ticker.ETH_USD, Decimal("3"), 4_000_000_001)
                    latest = await repository.get_latest(Ticker.BTC_USD)
                    assert latest is not None and latest.id == second.id
                    records = await repository.list_between(
                        Ticker.BTC_USD, 4_000_000_000, 4_000_000_001
                    )
                    assert [record.id for record in records] == [second.id, first_id]
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
