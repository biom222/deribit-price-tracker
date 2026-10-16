import logging
from collections.abc import AsyncIterator
from socket import gaierror
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.price import PriceRepository
from app.services.prices import PriceService

logger = logging.getLogger(__name__)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    try:
        async with request.app.state.session_factory() as session:
            yield session
    except (ConnectionError, TimeoutError, gaierror) as exc:
        logger.exception("Database connection failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from exc


def get_price_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PriceService:
    return PriceService(PriceRepository(session))


PriceServiceDependency = Annotated[PriceService, Depends(get_price_service)]
