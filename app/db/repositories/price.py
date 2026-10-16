from decimal import Decimal

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tickers import Ticker
from app.db.models.price import PriceRecord


class PriceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        ticker: Ticker,
        price: Decimal,
        timestamp: int,
    ) -> PriceRecord:
        record = PriceRecord(ticker=ticker.value, price=price, timestamp=timestamp)
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return record

    async def list_by_ticker(self, ticker: Ticker) -> list[PriceRecord]:
        statement = self._base_query(ticker).order_by(
            PriceRecord.timestamp.desc(), PriceRecord.id.desc()
        )
        result = await self._session.scalars(statement)
        return list(result.all())

    async def get_latest(self, ticker: Ticker) -> PriceRecord | None:
        statement = self._base_query(ticker).order_by(
            PriceRecord.timestamp.desc(), PriceRecord.id.desc()
        )
        return await self._session.scalar(statement.limit(1))

    async def list_between(
        self,
        ticker: Ticker,
        start_timestamp: int,
        end_timestamp: int,
    ) -> list[PriceRecord]:
        statement = (
            self._base_query(ticker)
            .where(
                PriceRecord.timestamp >= start_timestamp,
                PriceRecord.timestamp < end_timestamp,
            )
            .order_by(PriceRecord.timestamp.desc(), PriceRecord.id.desc())
        )
        result = await self._session.scalars(statement)
        return list(result.all())

    @staticmethod
    def _base_query(ticker: Ticker) -> Select[tuple[PriceRecord]]:
        return select(PriceRecord).where(PriceRecord.ticker == ticker.value)
