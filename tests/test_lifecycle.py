from socket import gaierror
from unittest.mock import AsyncMock, Mock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.api.dependencies import get_price_service
from app.main import create_app


@pytest.mark.asyncio
async def test_application_disposes_owned_engine_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = Mock(dispose=AsyncMock())
    factory = Mock()
    monkeypatch.setattr(
        "app.main.get_settings", lambda: Mock(database_url="unused", log_level="INFO")
    )
    monkeypatch.setattr("app.main.create_engine", lambda url: engine)
    monkeypatch.setattr("app.main.create_session_factory", lambda value: factory)
    application = create_app()
    with pytest.raises(RuntimeError, match="test failure"):
        async with application.router.lifespan_context(application):
            assert application.state.session_factory is factory
            raise RuntimeError("test failure")
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_application_does_not_create_engine_for_injected_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_engine = Mock()
    monkeypatch.setattr("app.main.create_engine", create_engine)
    factory = Mock()
    application = create_app(factory)
    async with application.router.lifespan_context(application):
        assert application.state.session_factory is factory
    create_engine.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (OperationalError("SELECT", {}, Exception("connection failed")), 503),
        (ProgrammingError("SELECT", {}, Exception("invalid SQL")), 500),
    ],
)
async def test_database_errors_are_classified(
    error: Exception, expected_status: int
) -> None:
    service = Mock(get_all=AsyncMock(side_effect=error))
    application = create_app(Mock())
    application.dependency_overrides[get_price_service] = lambda: service
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(application, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/v1/prices", params={"ticker": "btc_usd"})
    assert response.status_code == expected_status
    assert "connection failed" not in response.text
    assert "invalid SQL" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [ConnectionRefusedError(), TimeoutError(), gaierror()]
)
async def test_raw_database_connection_errors_return_503(error: Exception) -> None:
    context = AsyncMock()
    context.__aenter__.side_effect = error
    application = create_app(Mock(return_value=context))
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(application), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/prices", params={"ticker": "btc_usd"})
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
