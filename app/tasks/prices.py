import asyncio
import logging
import time

from app.clients.deribit import DeribitClient, DeribitClientError
from app.core.celery import celery_app
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.tickers import Ticker
from app.db.repositories.price import PriceRepository
from app.db.session import create_engine, create_session_factory

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.prices.collect_index_prices")
def collect_index_prices() -> None:
    asyncio.run(_collect_index_prices())


async def _collect_index_prices() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    try:
        async with DeribitClient(
            base_url=str(settings.deribit_base_url),
            timeout_seconds=settings.deribit_timeout_seconds,
        ) as client:
            for ticker in Ticker:
                try:
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
                except DeribitClientError:
                    logger.exception("Failed to fetch price for %s", ticker.value)
                except Exception:
                    logger.exception("Failed to persist price for %s", ticker.value)
    finally:
        await engine.dispose()
