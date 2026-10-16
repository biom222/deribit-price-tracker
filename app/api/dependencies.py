from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.price import PriceRepository
from app.services.prices import PriceService


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


def get_price_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PriceService:
    return PriceService(PriceRepository(session))


PriceServiceDependency = Annotated[PriceService, Depends(get_price_service)]
