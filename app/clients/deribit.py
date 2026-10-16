import logging
from decimal import Decimal, InvalidOperation
from types import TracebackType
from typing import Any, Self

import aiohttp

from app.core.tickers import Ticker

logger = logging.getLogger(__name__)


class DeribitClientError(RuntimeError):
    """Raised when Deribit cannot provide a valid index price."""


class DeribitClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 10.0,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._session = session
        self._owns_session = False

    async def __aenter__(self) -> Self:
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
            self._owns_session = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None
            self._owns_session = False

    async def get_index_price(self, ticker: Ticker) -> Decimal:
        if self._session is None:
            raise RuntimeError("DeribitClient must be used as an async context manager")

        url = f"{self._base_url}/public/get_index_price"
        try:
            async with self._session.get(
                url,
                params={"index_name": ticker.value},
                timeout=self._timeout,
            ) as response:
                if response.status != 200:
                    raise DeribitClientError(
                        f"Deribit returned HTTP {response.status} for {ticker.value}"
                    )
                payload = await response.json()
        except DeribitClientError:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            logger.warning("Deribit request failed for %s: %s", ticker.value, exc)
            raise DeribitClientError(
                f"Unable to fetch Deribit price for {ticker.value}"
            ) from exc

        price = self._parse_price(payload, ticker)
        logger.info("Fetched %s index price: %s", ticker.value, price)
        return price

    @staticmethod
    def _parse_price(payload: Any, ticker: Ticker) -> Decimal:
        if not isinstance(payload, dict):
            raise DeribitClientError(
                f"Unexpected Deribit response for {ticker.value}: object expected"
            )

        result = payload.get("result")
        raw_price = result.get("index_price") if isinstance(result, dict) else None
        if isinstance(raw_price, bool) or raw_price is None:
            raise DeribitClientError(
                f"Unexpected Deribit response for {ticker.value}: index_price missing"
            )

        try:
            price = Decimal(str(raw_price))
        except (InvalidOperation, ValueError) as exc:
            raise DeribitClientError(
                f"Unexpected Deribit index_price for {ticker.value}"
            ) from exc

        if not price.is_finite() or price <= 0:
            raise DeribitClientError(
                f"Unexpected Deribit index_price for {ticker.value}"
            )
        return price
