from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.dependencies import PriceServiceDependency
from app.core.tickers import Ticker
from app.schemas.price import PriceResponse

router = APIRouter(prefix="/prices", tags=["prices"])
TickerQuery = Annotated[Ticker, Query(description="Supported Deribit index name")]


@router.get("", response_model=list[PriceResponse])
async def get_prices(
    ticker: TickerQuery,
    service: PriceServiceDependency,
) -> list[PriceResponse]:
    records = await service.get_all(ticker)
    return [PriceResponse.model_validate(record) for record in records]


@router.get("/latest", response_model=PriceResponse)
async def get_latest_price(
    ticker: TickerQuery,
    service: PriceServiceDependency,
) -> PriceResponse:
    record = await service.get_latest(ticker)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No prices found for {ticker.value}",
        )
    return PriceResponse.model_validate(record)


@router.get("/by-date", response_model=list[PriceResponse])
async def get_prices_by_date(
    ticker: TickerQuery,
    service: PriceServiceDependency,
    target_date: Annotated[
        date,
        Query(alias="date", description="UTC calendar date in YYYY-MM-DD format"),
    ],
) -> list[PriceResponse]:
    records = await service.get_by_date(ticker, target_date)
    return [PriceResponse.model_validate(record) for record in records]
