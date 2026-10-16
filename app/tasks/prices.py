import asyncio
import logging
import time

from sqlalchemy.exc import SQLAlchemyError

from app.clients.deribit import DeribitClient, DeribitClientError
from app.core.celery import celery_app
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.tickers import Ticker
from app.db.repositories.price import PriceRepository
from app.db.session import create_engine, create_session_factory

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.prices.collect_index_prices",
    soft_time_limit=55,
    time_limit=60,
    ignore_result=True,
)
def collect_index_prices() -> None:
    asyncio.run(_collect_index_prices())


async def _collect_index_prices() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    try:
        errors: list[Exception] = []
        async with DeribitClient(
            base_url=str(settings.deribit_base_url),
            timeout_seconds=settings.deribit_timeout_seconds,
        ) as client:
            for ticker in Ticker:
                try:
                    async with asyncio.timeout(25):
                        price = await client.get_index_price(ticker)
                        received_at = int(time.time())
                        async with session_factory() as session:
                            record = await PriceRepository(session).add(
                                ticker=ticker,
                                price=price,
                                timestamp=received_at,
                            )
                    logger.info(
                        "Persisted price record id=%s ticker=%s timestamp=%s",
                        record.id,
                        ticker.value,
                        received_at,
                    )
                except (DeribitClientError, SQLAlchemyError, OSError) as exc:
                    errors.append(exc)
                    logger.exception("Failed to collect price for %s", ticker.value)
        if errors:
            raise ExceptionGroup("Price collection failed", errors)
    finally:
        await engine.dispose()
