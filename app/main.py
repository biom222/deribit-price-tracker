import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DisconnectionError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as DatabaseTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.routes import prices_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import create_engine, create_session_factory

logger = logging.getLogger(__name__)


def create_app(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if session_factory is not None:
            application.state.session_factory = session_factory
            yield
            return

        settings = get_settings()
        configure_logging(settings.log_level)
        engine = create_engine(settings.database_url)
        application.state.session_factory = create_session_factory(engine)
        try:
            yield
        finally:
            await engine.dispose()

    application = FastAPI(
        title="Deribit Price Tracker",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    application.include_router(prices_router, prefix="/api/v1")

    @application.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.exception_handler(OperationalError)
    @application.exception_handler(InterfaceError)
    @application.exception_handler(DisconnectionError)
    @application.exception_handler(DatabaseTimeoutError)
    async def database_error_handler(
        request: Request,
        exception: Exception,
    ) -> JSONResponse:
        logger.exception("Database operation failed for %s", request.url.path)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Database unavailable"},
        )

    return application


app = create_app()
