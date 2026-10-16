from datetime import UTC, date, datetime, time

from app.core.tickers import Ticker
from app.db.models.price import PriceRecord
from app.db.repositories.price import PriceRepository


class PriceService:
    def __init__(self, repository: PriceRepository) -> None:
        self._repository = repository

    async def get_all(self, ticker: Ticker) -> list[PriceRecord]:
        return await self._repository.list_by_ticker(ticker)

    async def get_latest(self, ticker: Ticker) -> PriceRecord | None:
        return await self._repository.get_latest(ticker)

    async def get_by_date(
        self,
        ticker: Ticker,
        target_date: date,
    ) -> list[PriceRecord]:
        start = datetime.combine(target_date, time.min, tzinfo=UTC)
        start_timestamp = int(start.timestamp())
        return await self._repository.list_between(
            ticker,
            start_timestamp,
            start_timestamp + 86_400,
        )
