from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.core.tickers import Ticker


class PriceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: Ticker
    price: Decimal
    timestamp: int
